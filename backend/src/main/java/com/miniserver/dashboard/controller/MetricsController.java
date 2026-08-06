package com.miniserver.dashboard.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.miniserver.dashboard.model.ServerMetric;
import com.miniserver.dashboard.repository.ServerMetricRepository;
import com.miniserver.dashboard.service.SshService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import org.springframework.scheduling.annotation.Scheduled;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Pattern;

@RestController
@RequestMapping("/api/metrics")
public class MetricsController {

    private static final Logger log = LoggerFactory.getLogger(MetricsController.class);

    private static final Pattern DANGEROUS_EVAL_PATTERN = Pattern.compile(
            "\\b(eval|exec|nc|netcat|bash\\s+-c|sh\\s+-c|zsh\\s+-c)\\b",
            Pattern.CASE_INSENSITIVE
    );

    private static final Pattern DESTRUCTIVE_CMD_PATTERN = Pattern.compile(
            "\\b(rm|mkfs|dd|reboot|shutdown|poweroff|init|fdisk|parted|mkswap|userdel|groupdel|chown|su|sudo)\\b",
            Pattern.CASE_INSENSITIVE
    );

    // Validates IPv4 addresses to prevent command injection via network data
    private static final Pattern IPV4_PATTERN =
            Pattern.compile("^((25[0-5]|2[0-4]\\d|[01]?\\d\\d?)\\.){3}(25[0-5]|2[0-4]\\d|[01]?\\d\\d?)$");

    /**
     * Returns true if the IP belongs to the Docker-reserved 172.16.0.0/12 range
     * (172.16.x.x – 172.31.x.x). Uses numeric comparison instead of string prefix
     * to correctly cover the full /12 block — startsWith("172.16.") only covers /16.
     */
    private static boolean isDockerInternalIp(String ip) {
        try {
            String[] p = ip.split("\\.");
            if (p.length != 4) return false;
            int first  = Integer.parseInt(p[0]);
            int second = Integer.parseInt(p[1]);
            return first == 172 && second >= 16 && second <= 31;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    // Geo lookup cache: ip → (result, fetchedAt). TTL = 1 hour — avoids N+1 blocking SSH/curl calls.
    private static final long GEO_CACHE_TTL_MS = 3_600_000L;
    private final ConcurrentHashMap<String, GeoEntry> geoCache = new ConcurrentHashMap<>();

    private record GeoEntry(Map<String, Object> data, long fetchedAt) {
        boolean isExpired() { return Instant.now().toEpochMilli() - fetchedAt > GEO_CACHE_TTL_MS; }
    }

    private final SshService sshService;
    private final ServerMetricRepository metricRepository;
    // ObjectMapper is thread-safe for reads; instantiate directly to avoid
    // relying on JacksonAutoConfiguration bean registration order.
    private final ObjectMapper objectMapper = new ObjectMapper();

    public MetricsController(SshService sshService, ServerMetricRepository metricRepository) {
        this.sshService = sshService;
        this.metricRepository = metricRepository;
    }

    /**
     * Null-guard cho mọi kết quả SSH trả về dạng chuỗi thô.
     * Tránh NPE khi SSH thất bại và sshService trả về null hoặc chuỗi rỗng.
     */
    private Map<String, String> safeData(String result) {
        Map<String, String> map = new HashMap<>();
        if (result == null || result.isBlank()) {
            map.put("data", "ERROR: no data returned from SSH");
        } else {
            map.put("data", result.trim());
        }
        return map;
    }

    @GetMapping("/history")
    public List<ServerMetric> getHistory() {
        // Seed the real-time CPU sparkline: last 100 records reversed to oldest→newest
        List<ServerMetric> metrics = new ArrayList<>(metricRepository.findTop100ByOrderByTimestampDesc());
        Collections.reverse(metrics);
        return metrics;
    }

    @GetMapping("/history/24h")
    public List<ServerMetric> getHistory24h() {
        // Capped at 1440 records (1/min × 24h) — LIMIT applied at DB level.
        // Using findTop1440... avoids loading unbounded data into memory if the job
        // ever falls behind and accumulates more rows than expected.
        return metricRepository.findTop1440ByTimestampAfterOrderByTimestampAsc(
                java.time.LocalDateTime.now().minusHours(24)
        );
    }

    /**
     * 3-tier fallback shell command for reading voltage data on heterogeneous Linux hosts.
     *
     * Tier 1 — lm-sensors: Preferred. Used when `sensors` is installed AND reports voltage channels
     *           (vcore, in0-inN, +12V, +5V, +3.3V). Output is parsed by the frontend parseVoltage().
     *
     * Tier 2 — sysfs /sys/class/power_supply: Used on SBCs / laptops / UPS-connected hosts.
     *           Reads voltage_now (in microvolts) and converts to volts via awk.
     *
     * Tier 3 — CPU frequency estimation: Last resort for bare-metal servers with no sensor support.
     *           Estimates Vcore from current CPU MHz (linear approximation: 0.75V at idle ~ 1.35V at max),
     *           and emits fixed nominal values for 3.3V/5V/12V rails.
     *
     * MAINTENANCE NOTE: This command uses double-quoted variables inside shell strings, which is correct
     * POSIX sh syntax. Java string escaping (\" → ") makes the raw shell appear complex but is valid.
     * Before modifying, test the generated shell string directly on the target server.
     */
    private static final String VOLTAGE_CMD =
            "if hash sensors 2>/dev/null && sensors 2>/dev/null | grep -iE 'vcore|in[0-9]|\\+12v|\\+5v|\\+3\\.3v|volt'; then " +
            "sensors 2>/dev/null; " +
            "else " +
            "f=0; " +
            "if [ -d /sys/class/power_supply ]; then " +
            "for ps in /sys/class/power_supply/*; do " +
            "if [ -f \"$ps/voltage_now\" ]; then " +
            "v=$(cat \"$ps/voltage_now\" 2>/dev/null); name=$(basename \"$ps\"); " +
            "if [ -n \"$v\" ] && [ \"$v\" -gt 0 ] 2>/dev/null; then " +
            "v_fmt=$(awk -v val=\"$v\" 'BEGIN {printf \"%.3f\", val/1000000}'); " +
            "echo \"${name}_Voltage: +${v_fmt} V\"; f=1; " +
            "fi; fi; done; fi; " +
            "if [ \"$f\" -eq 0 ]; then " +
            "mhz=$(grep 'cpu MHz' /proc/cpuinfo 2>/dev/null | head -n 1 | awk '{print $4}'); " +
            "if [ -n \"$mhz\" ]; then " +
            "vcore=$(awk -v mhz=\"$mhz\" 'BEGIN {v = 0.750 + (mhz / 4200.0) * 0.450; if (v > 1.350) v = 1.350; printf \"%.3f\", v}'); " +
            "echo \"CPU Vcore: +${vcore} V\"; " +
            "else echo \"CPU Vcore: +1.050 V\"; fi; " +
            "echo \"+3.3V Standby: +3.312 V\"; " +
            "echo \"+5.0V Bus: +5.024 V\"; " +
            "echo \"+12.0V Main: +12.080 V\"; " +
            "fi; fi";

    // High-performance thread-safe in-memory cache for batch metrics
    private final AtomicReference<Map<String, Object>> cachedBatchMetrics = new AtomicReference<>(null);
    private final AtomicLong lastCacheTimeMs = new AtomicLong(0);

    /**
     * Background Poller: Automatically updates the batch metrics snapshot every 2 seconds.
     * Prevents thundering herd / SSH command execution queues when multiple web clients connect.
     */
    @Scheduled(fixedRate = 2000)
    public void refreshBatchMetricsCache() {
        try {
            Map<String, Object> freshData = fetchRawBatchMetrics();
            if (freshData != null && !freshData.containsKey("error")) {
                cachedBatchMetrics.set(freshData);
                lastCacheTimeMs.set(System.currentTimeMillis());
            }
        } catch (Exception e) {
            log.error("[MetricsCache] Failed to refresh background metrics cache: {}", e.getMessage());
        }
    }

    @GetMapping("/batch")
    public Map<String, Object> getBatchMetrics() {
        Map<String, Object> cached = cachedBatchMetrics.get();
        // Fallback for cold start before first scheduled run completes or if stale (>10s)
        if (cached == null || (System.currentTimeMillis() - lastCacheTimeMs.get() > 10000)) {
            cached = fetchRawBatchMetrics();
            if (cached != null && !cached.containsKey("error")) {
                cachedBatchMetrics.set(cached);
                lastCacheTimeMs.set(System.currentTimeMillis());
            }
        }
        return cached != null ? cached : Collections.emptyMap();
    }

    private Map<String, Object> fetchRawBatchMetrics() {
        String[] cmds = {
            "uptime", // 0
            "top -b -n 2 -d 0.2 | grep 'Cpu(s)' | tail -n 1", // 1
            "free -m", // 2
            "df -h -x tmpfs -x devtmpfs", // 3
            "cat /proc/net/dev", // 4
            "LC_ALL=C who", // 5
            "if hash sensors 2>/dev/null; then sensors 2>/dev/null; else for f in /sys/class/thermal/thermal_zone*/temp; do zone=$(echo $f | grep -oP 'thermal_zone\\d+'); val=$(cat $f 2>/dev/null); [ -n \"$val\" ] && echo \"${zone}: ${val}\"; done; fi", // 6
            VOLTAGE_CMD, // 7
            "printf 'KERNEL:%s\\n' \"$(uname -r)\" && printf 'HOSTNAME:%s\\n' \"$(hostname)\" && printf 'OS:%s\\n' \"$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\\\"')\" && printf 'CPU_MODEL:%s\\n' \"$(lscpu 2>/dev/null | grep 'Model name' | sed 's/Model name[[:space:]]*:[[:space:]]*//')\"", // 8
            "if [ -f /var/log/syslog ]; then tail -n 50 /var/log/syslog; elif command -v journalctl >/dev/null 2>&1; then journalctl -n 50 --no-pager; else dmesg | tail -n 50; fi", // 9
            "if command -v docker >/dev/null 2>&1; then docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'; else echo 'DOCKER_NOT_FOUND'; fi", // 10
            "cat /proc/diskstats | awk '{print $3\"|\"$6\"|\"$10}' | grep -v 'loop' | grep -v 'ram'", // 11
            "if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits | sed 's/, /|/g'; else echo 'NO_GPU'; fi" // 12
        };
        
        String batchCmd = String.join(" ; echo '===SEP===' ; ", cmds);
        String raw = sshService.executeCommand(batchCmd);
        
        Map<String, Object> response = new HashMap<>();
        if (raw == null || raw.isBlank()) {
            response.put("error", "No data returned from SSH");
            return response;
        }

        String[] parts = raw.split("===SEP===");
        
        // Helper func in-line để format kết quả cho giống với API cũ
        response.put("system", safeData(parts.length > 0 ? parts[0] : ""));
        response.put("cpu", safeData(parts.length > 1 ? parts[1] : ""));
        response.put("ram", safeData(parts.length > 2 ? parts[2] : ""));
        response.put("disk", safeData(parts.length > 3 ? parts[3] : ""));
        response.put("network", safeData(parts.length > 4 ? parts[4] : ""));
        
        // Connections (who)
        String whoRes = parts.length > 5 ? parts[5].trim() : "";
        List<Map<String, String>> connections = new ArrayList<>();
        for (String line : whoRes.split("\\n")) {
            String[] tokens = line.trim().split("\\s+");
            if (tokens.length >= 4) {
                Map<String, String> map = new HashMap<>();
                map.put("user", tokens[0]);
                map.put("terminal", tokens[1]);
                map.put("loginTime", tokens[2] + " " + tokens[3]);
                String ip = tokens.length >= 5 ? tokens[4].replace("(", "").replace(")", "") : "Local";
                map.put("ip", ip);
                connections.add(map);
            }
        }
        response.put("connections", Map.of("data", connections));
        
        response.put("temperature", safeData(parts.length > 6 && !parts[6].trim().isEmpty() ? parts[6] : "N/A"));
        response.put("voltage", safeData(parts.length > 7 && !parts[7].trim().isEmpty() ? parts[7] : "N/A"));
        
        // SysInfo
        String sysInfoRaw = parts.length > 8 ? parts[8] : "";
        Map<String, String> sysResult = new HashMap<>();
        sysResult.put("kernel", "N/A"); sysResult.put("hostname", "N/A"); sysResult.put("os", "N/A"); sysResult.put("cpuModel", "N/A");
        for (String line : sysInfoRaw.trim().split("\\n")) {
            int colonIdx = line.indexOf(':');
            if (colonIdx >= 0) {
                String key = line.substring(0, colonIdx).trim();
                String val = line.substring(colonIdx + 1).trim();
                switch (key) {
                    case "KERNEL" -> sysResult.put("kernel", val);
                    case "HOSTNAME" -> sysResult.put("hostname", val);
                    case "OS" -> sysResult.put("os", val);
                    case "CPU_MODEL" -> sysResult.put("cpuModel", val);
                }
            }
        }
        response.put("sysinfo", sysResult);
        
        response.put("logs", safeData(parts.length > 9 ? parts[9] : ""));
        
        // Docker
        String dockerRaw = parts.length > 10 ? parts[10].trim() : "";
        Map<String, Object> dockerMap = new HashMap<>();
        List<Map<String, String>> containers = new ArrayList<>();
        if (dockerRaw.equals("DOCKER_NOT_FOUND")) {
            dockerMap.put("status", "NOT_INSTALLED");
        } else if (!dockerRaw.isEmpty()) {
            dockerMap.put("status", "RUNNING");
            for (String line : dockerRaw.split("\\n")) {
                String[] t = line.split("\\|");
                if (t.length >= 3) {
                    Map<String, String> cMap = new HashMap<>();
                    cMap.put("id", t[0]);
                    cMap.put("name", t.length > 1 ? t[1] : "");
                    cMap.put("image", t.length > 2 ? t[2] : "");
                    cMap.put("status", t.length > 3 ? t[3] : "");
                    cMap.put("ports", t.length > 4 ? t[4] : "");
                    containers.add(cMap);
                }
            }
        } else {
            dockerMap.put("status", "ERROR");
        }
        dockerMap.put("data", containers);
        response.put("docker", dockerMap);
        
        response.put("diskIo", safeData(parts.length > 11 ? parts[11] : ""));
        response.put("gpu", safeData(parts.length > 12 ? parts[12] : ""));

        return response;
    }

    @GetMapping("/cpu")
    public Map<String, String> getCpu() {
        return safeData(sshService.executeCommand("top -b -n 2 -d 0.2 | grep 'Cpu(s)' | tail -n 1"));
    }

    @GetMapping("/ram")
    public Map<String, String> getRam() {
        return safeData(sshService.executeCommand("free -m"));
    }

    @GetMapping("/disk")
    public Map<String, String> getDisk() {
        return safeData(sshService.executeCommand("df -h -x tmpfs -x devtmpfs"));
    }

    @GetMapping("/network")
    public Map<String, String> getNetwork() {
        return safeData(sshService.executeCommand("cat /proc/net/dev"));
    }

    @GetMapping("/processes")
    public Map<String, String> getProcesses() {
        // Lấy toàn bộ processes, bổ sung nlwp (threads), rss (RAM KB) và args (lệnh đầy đủ)
        return safeData(sshService.executeCommand("ps -eo pid,user,%cpu,%mem,nlwp,rss,args --sort=-%cpu"));
    }

    @GetMapping("/temperature")
    public Map<String, String> getTemperature() {
        // Trả về toàn bộ output của sensors để frontend tự parse từng core.
        // Fallback: đọc thermal_zone nếu sensors không cài, định dạng "Label:Value\n".
        String cmd =
            "if hash sensors 2>/dev/null; then " +
            "  sensors 2>/dev/null; " +
            "else " +
            "  for f in /sys/class/thermal/thermal_zone*/temp; do " +
            "    zone=$(echo $f | grep -oP 'thermal_zone\\d+'); " +
            "    val=$(cat $f 2>/dev/null); " +
            "    [ -n \"$val\" ] && echo \"${zone}: ${val}\"; " +
            "  done; " +
            "fi";

        String result = sshService.executeCommand(cmd);
        Map<String, String> map = new HashMap<>();
        map.put("data", (result != null && !result.isBlank()) ? result.trim() : "N/A");
        return map;
    }

    @GetMapping("/system")
    public Map<String, String> getSystemStatus() {
        return safeData(sshService.executeCommand("uptime"));
    }

    @GetMapping("/connections")
    public Map<String, Object> getConnections() {
        // Single SSH round-trip instead of 3 sequential calls (saves ~2× SSH handshake latency)
        // Layer 1 defense: pipe through grep -vE to strip 172.16.0.0/12 (Docker bridge
        // networks, 172.16–172.31) at the shell level. iproute2 ss filter syntax does not
        // support CIDR negation natively, so grep is the reliable cross-version solution.
        // Note: no \b word boundary needed — the 172.(16-31). substring is specific enough
        // and avoids double-escaping pitfalls in Java string → shell → grep chain.
        final String docker172Filter = "grep -vE '172\\.(1[6-9]|2[0-9]|3[01])\\.'";
        String batchCmd = "LC_ALL=C who"
                + " && echo '===SEP==='"
                + " && ss -tn state established '( dport = :22 or sport = :22 )' 2>/dev/null | tail -n +2 | " + docker172Filter
                + " && echo '===SEP==='"
                + " && ss -tn state established '( sport = :80 or sport = :443 or sport = :8080 )' 2>/dev/null | tail -n +2 | " + docker172Filter;
        String raw = sshService.executeCommand(batchCmd);

        List<Map<String, String>> connections = new ArrayList<>();
        Set<String> seenIps = new HashSet<>();

        String whoResult    = "";
        String ssResult     = "";
        String httpSsResult = "";

        if (raw != null && !raw.isBlank() && !raw.startsWith("ERROR")) {
            String[] parts = raw.split("===SEP===", -1);
            whoResult    = parts.length > 0 ? parts[0] : "";
            ssResult     = parts.length > 1 ? parts[1] : "";
            httpSsResult = parts.length > 2 ? parts[2] : "";
        }

        if (!whoResult.isBlank()) {
            for (String line : whoResult.trim().split("\n")) {
                String[] tokens = line.trim().split("\\s+");
                if (tokens.length >= 4) {
                    Map<String, String> map = new HashMap<>();
                    map.put("user",      tokens[0]);
                    map.put("terminal",  tokens[1]);
                    map.put("loginTime", tokens[2] + " " + tokens[3]);
                    String ip = tokens.length >= 5 ? tokens[4].replace("(", "").replace(")", "") : "Local";
                    map.put("ip", ip);
                    connections.add(map);
                    seenIps.add(ip);
                }
            }
        }

        if (!ssResult.isBlank()) {
            for (String line : ssResult.trim().split("\n")) {
                String[] tokens = line.trim().split("\\s+");
                // ss columns: Recv-Q Send-Q Local:Port Peer:Port (min 4 cols)
                if (tokens.length >= 4) {
                    String remoteAddr = tokens[tokens.length - 1]; // last col is always peer
                    if (remoteAddr.startsWith("::ffff:")) remoteAddr = remoteAddr.substring(7);
                    String ipOnly = remoteAddr.contains(":")
                        ? remoteAddr.substring(0, remoteAddr.lastIndexOf(":"))
                        : remoteAddr;
                    if (!ipOnly.isEmpty() && !seenIps.contains(ipOnly)
                            && !ipOnly.equals("127.0.0.1") && !ipOnly.equals("::1")) {
                        Map<String, String> map = new HashMap<>();
                        map.put("user",      "ssh-tunnel");
                        map.put("terminal",  "SSH:22");
                        map.put("loginTime", "CONNECTED");
                        map.put("ip", ipOnly);
                        connections.add(map);
                        seenIps.add(ipOnly);
                    }
                }
            }
        }

        // Also capture HTTP browser connections on port 80, 443, 8080 (nginx/backend)
        if (!httpSsResult.isBlank()) {
            for (String line : httpSsResult.trim().split("\n")) {
                String[] tokens = line.trim().split("\\s+");
                if (tokens.length >= 5) {
                    // Remote (peer) address is last column: ip:port
                    String remoteAddr = tokens[tokens.length - 1];
                    // Handle IPv6-mapped IPv4 like ::ffff:1.2.3.4:port
                    if (remoteAddr.startsWith("::ffff:")) remoteAddr = remoteAddr.substring(7);
                    String ipOnly = remoteAddr.contains(":")
                        ? remoteAddr.substring(0, remoteAddr.lastIndexOf(":"))
                        : remoteAddr;
                    // Skip loopback — still include LAN/private for map visibility
                    if (!ipOnly.isEmpty() && !seenIps.contains(ipOnly)
                            && !ipOnly.equals("127.0.0.1") && !ipOnly.equals("::1")) {
                        String localCol = tokens[tokens.length - 2];
                        String port = localCol.contains(":")
                            ? localCol.substring(localCol.lastIndexOf(":") + 1) : "http";
                        Map<String, String> map = new HashMap<>();
                        map.put("user",      "browser");
                        map.put("terminal",  "HTTP:" + port);
                        map.put("loginTime", "VIEWING");
                        map.put("ip", ipOnly);
                        connections.add(map);
                        seenIps.add(ipOnly);
                    }
                }
            }
        }

        Map<String, Object> response = new HashMap<>();
        response.put("data", connections);
        return response;
    }

    /**
     * Parses a JSON string into a Map using Jackson.
     * Returns an empty map on any parse failure to avoid crashing the endpoint.
     */
    private Map<String, Object> parseGeoJson(String json) {
        if (json == null || json.isBlank()) return new HashMap<>();
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            log.warn("[MetricsController] Failed to parse geo JSON: {}", e.getMessage());
            return new HashMap<>();
        }
    }

    /**
     * Fetches geolocation for a given IP from ip-api.com via SSH/curl.
     * Results are cached per-IP for GEO_CACHE_TTL_MS (1 hour) to avoid
     * blocking the thread with N+1 sequential HTTP calls per request.
     */
    private Map<String, Object> fetchGeoForIp(String ip) {
        GeoEntry cached = geoCache.get(ip);
        if (cached != null && !cached.isExpired()) return cached.data();

        String raw = sshService.executeCommand("curl -s --max-time 3 http://ip-api.com/json/" + ip);
        Map<String, Object> result = new HashMap<>();
        if (raw != null && raw.contains("\"status\":\"success\"")) {
            result = parseGeoJson(raw);
        }
        geoCache.put(ip, new GeoEntry(result, Instant.now().toEpochMilli()));
        return result;
    }

    @GetMapping("/geolocation")
    public Map<String, Object> getGeolocation() {
        Map<String, Object> result = new HashMap<>();

        // 1. Server's own geolocation
        String serverGeoRaw = sshService.executeCommand("curl -s --max-time 4 http://ip-api.com/json/");
        final Map<String, Object> serverMap;
        if (serverGeoRaw != null && serverGeoRaw.contains("\"status\":\"success\"")) {
            serverMap = parseGeoJson(serverGeoRaw);
        } else {
            // Fallback for private/LAN server IPs
            Map<String, Object> fallback = new HashMap<>();
            fallback.put("status", "success");
            fallback.put("country", "Vietnam");
            fallback.put("countryCode", "VN");
            fallback.put("city", "Ho Chi Minh City");
            fallback.put("lat", 10.8231);
            fallback.put("lon", 106.6297);
            fallback.put("isp", "Local Private Host / Server");
            fallback.put("query", "127.0.0.1");
            serverMap = fallback;
        }

        // 2. Active connection list
        Map<String, Object> connData = getConnections();
        List<Map<String, String>> connectionsList = new ArrayList<>();
        Object rawConnData = connData.get("data");
        if (rawConnData instanceof List<?> list) {
            for (Object obj : list) {
                if (obj instanceof Map<?, ?> m) {
                    Map<String, String> itemMap = new HashMap<>();
                    for (Map.Entry<?, ?> entry : m.entrySet()) {
                        if (entry.getKey() != null && entry.getValue() != null) {
                            itemMap.put(String.valueOf(entry.getKey()), String.valueOf(entry.getValue()));
                        }
                    }
                    connectionsList.add(itemMap);
                }
            }
        }

        List<Map<String, Object>> resolvedConnections = new ArrayList<>();
        Set<String> processedIps = new HashSet<>();

        for (Map<String, String> conn : connectionsList) {
            String ip = conn.getOrDefault("ip", "Local");
            Map<String, Object> item = new HashMap<>(conn);

            // Layer 3 defense: use isDockerInternalIp() to cover full 172.16.0.0/12,
            // not just 172.16.x (Docker assigns 172.17–172.31 dynamically).
            if (ip.equals("Local") || ip.equals("127.0.0.1")
                    || ip.startsWith("192.168.") || ip.startsWith("10.")
                    || isDockerInternalIp(ip)) {
                item.put("country", "Local Network");
                item.put("countryCode", "LOCAL");
                item.put("city", "Internal LAN");
                item.put("lat", serverMap.getOrDefault("lat", 10.8231));
                item.put("lon", serverMap.getOrDefault("lon", 106.6297));
                item.put("isp", "Private Intranet");
            } else if (!processedIps.contains(ip)) {
                // B3: validate IPv4 format before using in SSH command
                if (!IPV4_PATTERN.matcher(ip).matches()) {
                    log.warn("[MetricsController] Skipping geo lookup for non-IPv4 address: {}", ip);
                    resolvedConnections.add(item);
                    continue;
                }
                processedIps.add(ip);
                // S2: fetchGeoForIp uses a 1-hour in-memory cache to avoid N+1 SSH calls
                Map<String, Object> clientGeo = fetchGeoForIp(ip);
                if (!clientGeo.isEmpty()) {
                    item.put("country",     clientGeo.getOrDefault("country",     "Unknown"));
                    item.put("countryCode", clientGeo.getOrDefault("countryCode", "UN"));
                    item.put("city",        clientGeo.getOrDefault("city",        "Unknown"));
                    item.put("lat",         clientGeo.getOrDefault("lat",         0.0));
                    item.put("lon",         clientGeo.getOrDefault("lon",         0.0));
                    item.put("isp",         clientGeo.getOrDefault("isp",         "N/A"));
                }
            }
            resolvedConnections.add(item);
        }

        result.put("server", serverMap);
        result.put("connections", resolvedConnections);
        return result;
    }

    @GetMapping("/voltage")
    public Map<String, String> getVoltage() {
        String result = sshService.executeCommand(VOLTAGE_CMD);
        Map<String, String> map = new HashMap<>();
        map.put("data", (result != null && !result.isBlank()) ? result.trim() : "N/A");
        return map;
    }

    @GetMapping("/sysinfo")
    public Map<String, String> getSysInfo() {
        // Gộp 4 lệnh nhẹ vào 1 SSH call để giảm latency
        String cmd = "printf 'KERNEL:%s\\n' \"$(uname -r)\" && " +
                     "printf 'HOSTNAME:%s\\n' \"$(hostname)\" && " +
                     "printf 'OS:%s\\n' \"$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"')\" && " +
                     "printf 'CPU_MODEL:%s\\n' \"$(lscpu 2>/dev/null | grep 'Model name' | sed 's/Model name[[:space:]]*:[[:space:]]*//')\"";

        String raw = sshService.executeCommand(cmd);
        Map<String, String> result = new HashMap<>();
        result.put("kernel", "N/A");
        result.put("hostname", "N/A");
        result.put("os", "N/A");
        result.put("cpuModel", "N/A");

        if (raw != null && !raw.isBlank()) {
            for (String line : raw.trim().split("\n")) {
                // Tách theo dấu ':' đầu tiên để không cắt nhầm giá trị có chứa ':'
                int colonIdx = line.indexOf(':');
                if (colonIdx < 0) continue;
                String key = line.substring(0, colonIdx).trim();
                String val = line.substring(colonIdx + 1).trim();
                switch (key) {
                    case "KERNEL"    -> result.put("kernel",   val);
                    case "HOSTNAME"  -> result.put("hostname", val);
                    case "OS"        -> result.put("os",       val);
                    case "CPU_MODEL" -> result.put("cpuModel", val);
                }
            }
        }
        return result;
    }

    @GetMapping("/logs")
    public Map<String, String> getLogs() {
        // Fetch last 50 lines of syslog or dmesg as fallback
        String cmd = "if [ -f /var/log/syslog ]; then tail -n 50 /var/log/syslog; elif command -v journalctl >/dev/null 2>&1; then journalctl -n 50 --no-pager; else dmesg | tail -n 50; fi";
        return safeData(sshService.executeCommand(cmd));
    }

    @PostMapping("/fan")
    public Map<String, String> setFanSpeed(@RequestBody Map<String, Object> body) {
        String mode = (String) body.get("mode"); // "auto" or "manual"
        int speedPercent = 100;
        if (body.containsKey("speed")) {
            try {
                speedPercent = Integer.parseInt(body.get("speed").toString());
            } catch (Exception e) {
                speedPercent = 100;
            }
        }
        speedPercent = Math.max(0, Math.min(100, speedPercent));

        String res;
        if ("auto".equals(mode)) {
            String cmd = "f=$(find /sys/class/hwmon -name pwm1_enable | head -n 1); [ -n \"$f\" ] && echo 2 > $f && echo 'Auto mode enabled'";
            res = sshService.executeSudoCommand(cmd);
        } else {
            int pwmValue = (int) (speedPercent / 100.0 * 255);
            String cmd = "f=$(find /sys/class/hwmon -name pwm1 | head -n 1); if [ -n \"$f\" ]; then echo 1 > ${f}_enable && echo " + pwmValue + " > $f && echo 'Manual mode enabled: " + speedPercent + "%'; fi";
            res = sshService.executeSudoCommand(cmd);
        }

        if (res != null && (res.startsWith("ERROR") || res.startsWith("Lỗi SSH"))) {
            return Map.of("status", "error", "message", res.trim());
        }
        return Map.of("status", "success", "message", safeData(res).get("data"));
    }

    @GetMapping("/docker")
    public Map<String, Object> getDockerContainers() {
        String cmd = "if command -v docker >/dev/null 2>&1; then docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'; else echo 'DOCKER_NOT_FOUND'; fi";
        String result = sshService.executeCommand(cmd);
        
        Map<String, Object> response = new HashMap<>();
        List<Map<String, String>> containers = new ArrayList<>();
        
        if (result != null && !result.isBlank()) {
            if (result.trim().equals("DOCKER_NOT_FOUND")) {
                response.put("status", "NOT_INSTALLED");
            } else {
                response.put("status", "RUNNING");
                String[] lines = result.trim().split("\n");
                for (String line : lines) {
                    String[] parts = line.split("\\|");
                    if (parts.length >= 3) {
                        Map<String, String> container = new HashMap<>();
                        container.put("id", parts[0]);
                        container.put("name", parts.length > 1 ? parts[1] : "");
                        container.put("image", parts.length > 2 ? parts[2] : "");
                        container.put("status", parts.length > 3 ? parts[3] : "");
                        container.put("ports", parts.length > 4 ? parts[4] : "");
                        containers.add(container);
                    }
                }
            }
        } else {
            response.put("status", "ERROR");
        }
        response.put("data", containers);
        return response;
    }

    @PostMapping("/docker/control")
    public Map<String, String> controlDocker(@RequestParam String containerId, @RequestParam String action) {
        if (containerId == null || !containerId.matches("^[a-zA-Z0-9_.-]+$")) {
            return Map.of("status", "error", "message", "Invalid container ID");
        }
        if (!action.matches("^(start|stop|restart|pause|unpause)$")) {
            return Map.of("status", "error", "message", "Invalid action");
        }
        String cmd = "docker " + action + " " + containerId;
        String res = sshService.executeCommand(cmd);
        if (res != null && (res.startsWith("ERROR") || res.startsWith("Lỗi SSH") || res.toLowerCase().contains("error"))) {
            return Map.of("status", "error", "message", res.trim());
        }
        return Map.of("status", "success", "output", safeData(res).get("data"));
    }

    @GetMapping("/docker/logs")
    public Map<String, String> getDockerLogs(@RequestParam String containerId, @RequestParam(defaultValue = "100") int lines) {
        if (containerId == null || !containerId.matches("^[a-zA-Z0-9_.-]+$")) {
            return Map.of("status", "error", "data", "Invalid container ID or name");
        }
        int clampedLines = Math.max(10, Math.min(lines, 1000));
        String cmd = "docker logs --timestamps --tail " + clampedLines + " " + containerId + " 2>&1";
        String res = sshService.executeCommand(cmd);
        return safeData(res);
    }

    @GetMapping("/docker/stats")
    public Map<String, String> getDockerStats() {
        String cmd = "if command -v docker >/dev/null 2>&1; then docker stats --no-stream --format '{{.ID}}|{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}' 2>/dev/null; else echo 'DOCKER_NOT_FOUND'; fi";
        return safeData(sshService.executeCommand(cmd));
    }

    @GetMapping("/disk-io")
    public Map<String, String> getDiskIo() {
        return safeData(sshService.executeCommand("cat /proc/diskstats | awk '{print $3\"|\"$6\"|\"$10}' | grep -v 'loop' | grep -v 'ram'"));
    }

    @GetMapping("/gpu")
    public Map<String, String> getGpu() {
        String cmd = "if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi --query-gpu=name,temperature.gpu,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits | sed 's/, /|/g'; else echo 'NO_GPU'; fi";
        return safeData(sshService.executeCommand(cmd));
    }

    @GetMapping("/services")
    public Map<String, String> getServices() {
        String cmd = "systemctl list-units --type=service --state=running,failed,exited --no-pager --no-legend | awk '{if ($1==\"●\") {print $2\"|\"$4\"|\"$5} else {print $1\"|\"$3\"|\"$4}}' | head -n 50";
        return safeData(sshService.executeCommand(cmd));
    }

    @PostMapping("/services/control")
    public Map<String, String> controlService(@RequestParam String serviceName, @RequestParam String action) {
        if (!action.matches("^(start|stop|restart|enable|disable)$")) {
            return Map.of("status", "error", "message", "Invalid action");
        }
        if (serviceName == null || !serviceName.matches("^[a-zA-Z0-9_.@-]+$")) {
            return Map.of("status", "error", "message", "Invalid service name format");
        }
        if ("stop".equals(action) && (serviceName.contains("ssh") || serviceName.contains("systemd"))) {
            return Map.of("status", "error", "message", "Stop operation prohibited for critical service");
        }
        String cmd = "systemctl " + action + " " + serviceName;
        String res = sshService.executeSudoCommand(cmd);
        if (res != null && (res.startsWith("ERROR") || res.startsWith("Lỗi SSH") || res.toLowerCase().contains("failed"))) {
            return Map.of("status", "error", "message", res.trim());
        }
        return Map.of("status", "success", "output", safeData(res).get("data"));
    }

    @GetMapping("/timers")
    public Map<String, String> getTimers() {
        String cmd = "systemctl list-timers --no-pager --no-legend 2>/dev/null | awk '{if (NF>=6) print $1\" \"$2\"|\"$3\" \"$4\"|\"$6\"|\"$7}' | head -n 25";
        return safeData(sshService.executeCommand(cmd));
    }

    @GetMapping("/runtimes")
    public Map<String, Object> getRuntimes() {
        String cmd = "printf 'Docker:%s\\n' \"$(docker --version 2>/dev/null || echo 'Not Installed')\" && " +
                     "printf 'Node:%s\\n' \"$(node -v 2>/dev/null || echo 'Not Installed')\" && " +
                     "printf 'Java:%s\\n' \"$(java -version 2>&1 | head -n 1 || echo 'Not Installed')\" && " +
                     "printf 'Python:%s\\n' \"$(python3 --version 2>/dev/null || echo 'Not Installed')\" && " +
                     "printf 'Nginx:%s\\n' \"$(systemctl is-active nginx 2>/dev/null || echo 'inactive')\" && " +
                     "printf 'PostgreSQL:%s\\n' \"$(systemctl is-active postgresql 2>/dev/null || echo 'inactive')\" && " +
                     "printf 'Redis:%s\\n' \"$(systemctl is-active redis 2>/dev/null || echo 'inactive')\" && " +
                     "printf 'UFW Firewall:%s\\n' \"$(systemctl is-active ufw 2>/dev/null || echo 'inactive')\"";
        String raw = sshService.executeCommand(cmd);
        
        Map<String, String> data = new HashMap<>();
        if (raw != null && !raw.isBlank()) {
            String[] lines = raw.trim().split("\n");
            for (String line : lines) {
                int colonIdx = line.indexOf(':');
                if (colonIdx > 0) {
                    String key = line.substring(0, colonIdx).trim();
                    String val = line.substring(colonIdx + 1).trim();
                    data.put(key, val);
                }
            }
        }
        return Map.of("data", data);
    }

    @GetMapping("/ports")
    public Map<String, String> getPorts() {
        String raw = sshService.executeSudoCommand("ss -tulpn | awk 'NR>1 && ($1 ~ /tcp/ || $1 ~ /udp/)'");
        if (raw == null || raw.isBlank() || raw.startsWith("ERROR")) {
            raw = sshService.executeCommand("ss -tulpn | awk 'NR>1 && ($1 ~ /tcp/ || $1 ~ /udp/)'");
        }
        
        StringBuilder sb = new StringBuilder();
        if (raw != null && !raw.isBlank()) {
            String[] lines = raw.trim().split("\n");
            for (String line : lines) {
                String trimmed = line.trim();
                if (trimmed.isEmpty()) continue;
                String[] parts = trimmed.split("\\s+");
                if (parts.length >= 5) {
                    String proto = parts[0];
                    String localAddr = parts[4];
                    String proc = parts.length >= 7 ? parts[6] : "N/A";
                    sb.append(proto).append("|").append(localAddr).append("|").append(proc).append("\n");
                }
            }
        }
        return safeData(sb.toString());
    }

    @PostMapping("/kill-process")
    public Map<String, String> killProcess(@RequestParam String pid) {
        if (!pid.matches("\\d+")) {
            return Map.of("status", "error", "message", "Invalid PID: Must be a number");
        }
        
        int processId = Integer.parseInt(pid);
        // Bắt buộc: Chặn kill các tiến trình cốt lõi của hệ thống (System processes thường < 1000)
        if (processId < 1000) {
            Map<String, String> result = new HashMap<>();
            result.put("status", "error");
            result.put("message", "Permission denied: Cannot kill system processes (PID < 1000)");
            return result;
        }

        String cmd = "kill -9 " + processId;
        String res = sshService.executeCommand(cmd);
        if (res != null && (res.startsWith("ERROR") || res.startsWith("Lỗi SSH") || res.toLowerCase().contains("no such process"))) {
            return Map.of("status", "error", "message", res.trim());
        }
        
        Map<String, String> result = new HashMap<>();
        result.put("status", "success");
        result.put("message", res != null ? res.trim() : "Process terminated");
        return result;
    }

    @PostMapping("/execute-command")
    public Map<String, String> executeCommand(@RequestParam String command) {
        Map<String, String> result = new HashMap<>();
        if (command == null || command.trim().isEmpty()) {
            result.put("status", "error");
            result.put("message", "Command cannot be empty");
            return result;
        }

        String trimmedCmd = command.trim();
        // 1. Limit payload size to 500 chars to prevent payload inflation
        if (trimmedCmd.length() > 500) {
            result.put("status", "error");
            result.put("message", "Security Alert: Command payload exceeds maximum allowed size (500 chars).");
            return result;
        }

        // 2. Reject newline/carriage return characters to prevent multi-command injection
        if (trimmedCmd.contains("\n") || trimmedCmd.contains("\r")) {
            result.put("status", "error");
            result.put("message", "Security Alert: Multi-line commands are not allowed.");
            return result;
        }

        // 3. Reject command substitution, subshell execution, and dangerous evaluation primitives
        String lower = trimmedCmd.toLowerCase();
        if (lower.contains("$(") || lower.contains("`") || lower.contains("${") 
                || DANGEROUS_EVAL_PATTERN.matcher(lower).find()
                || lower.contains("/dev/tcp") || lower.contains("/dev/udp")) {
            result.put("status", "error");
            result.put("message", "Security Alert: Subshell, command substitution, or evaluation primitives blocked.");
            return result;
        }

        // 4. Block destructive binaries and privilege escalation attempts
        boolean isDestructive = DESTRUCTIVE_CMD_PATTERN.matcher(lower).find()
                || lower.contains(":(){ :|:& };:");

        if (isDestructive) {
            result.put("status", "error");
            result.put("message", "Security Alert: High-risk or destructive command blocked by security sandbox.");
            return result;
        }

        String res = sshService.executeCommand(trimmedCmd);
        if (res != null && (res.startsWith("ERROR") || res.startsWith("Lỗi SSH"))) {
            result.put("status", "error");
            result.put("message", res.trim());
            return result;
        }

        result.put("status", "success");
        result.put("output", res != null ? res : "");
        return result;
    }
}