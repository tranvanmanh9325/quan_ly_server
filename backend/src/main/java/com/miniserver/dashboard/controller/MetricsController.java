package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.model.ServerMetric;
import com.miniserver.dashboard.repository.ServerMetricRepository;
import com.miniserver.dashboard.service.SshService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

@RestController
@RequestMapping("/api/metrics")
public class MetricsController {

    private static final Pattern DANGEROUS_EVAL_PATTERN = Pattern.compile(
            "\\b(eval|exec|nc|netcat|bash\\s+-c|sh\\s+-c|zsh\\s+-c)\\b",
            Pattern.CASE_INSENSITIVE
    );

    private static final Pattern DESTRUCTIVE_CMD_PATTERN = Pattern.compile(
            "\\b(rm|mkfs|dd|reboot|shutdown|poweroff|init|fdisk|parted|mkswap|userdel|groupdel|chown|su|sudo)\\b",
            Pattern.CASE_INSENSITIVE
    );

    private final SshService sshService;
    private final ServerMetricRepository metricRepository;

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
        // Lấy tối đa 100 bản ghi gần nhất
        List<ServerMetric> metrics = new ArrayList<>(metricRepository.findTop100ByOrderByTimestampDesc());
        // Đảo ngược mảng để vẽ biểu đồ theo thứ tự thời gian tăng dần (cũ -> mới)
        Collections.reverse(metrics);
        return metrics;
    }

    @GetMapping("/batch")
    public Map<String, Object> getBatchMetrics() {
        String[] cmds = {
            "uptime", // 0
            "top -b -n 2 -d 0.3 | grep 'Cpu(s)' | tail -n 1", // 1
            "free -m", // 2
            "df -h -x tmpfs -x devtmpfs", // 3
            "cat /proc/net/dev", // 4
            "who", // 5
            "if hash sensors 2>/dev/null; then sensors 2>/dev/null; else for f in /sys/class/thermal/thermal_zone*/temp; do zone=$(echo $f | grep -oP 'thermal_zone\\d+'); val=$(cat $f 2>/dev/null); [ -n \"$val\" ] && echo \"${zone}: ${val}\"; done; fi", // 6
            "if hash sensors 2>/dev/null; then sensors 2>/dev/null; else echo 'N/A'; fi", // 7
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
        return safeData(sshService.executeCommand("top -b -n 2 -d 0.3 | grep 'Cpu(s)' | tail -n 1"));
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
        String whoResult = sshService.executeCommand("who");
        String ssResult = sshService.executeCommand("ss -tn state established '( dport = :22 or sport = :22 )' 2>/dev/null | tail -n +2");
        
        List<Map<String, String>> connections = new ArrayList<>();
        Set<String> seenIps = new HashSet<>();

        if (whoResult != null && !whoResult.isBlank() && !whoResult.startsWith("ERROR")) {
            String[] lines = whoResult.trim().split("\n");
            for (String line : lines) {
                String[] parts = line.trim().split("\\s+");
                if (parts.length >= 4) {
                    Map<String, String> map = new HashMap<>();
                    map.put("user", parts[0]);
                    map.put("terminal", parts[1]);
                    map.put("loginTime", parts[2] + " " + parts[3]);
                    String ip = parts.length >= 5 ? parts[4].replace("(", "").replace(")", "") : "Local";
                    map.put("ip", ip);
                    connections.add(map);
                    seenIps.add(ip);
                }
            }
        }

        if (ssResult != null && !ssResult.isBlank() && !ssResult.startsWith("ERROR")) {
            String[] lines = ssResult.trim().split("\n");
            for (String line : lines) {
                String[] parts = line.trim().split("\\s+");
                if (parts.length >= 5) {
                    String remoteAddr = parts[4];
                    String ipOnly = remoteAddr.contains(":") ? remoteAddr.substring(0, remoteAddr.lastIndexOf(":")) : remoteAddr;
                    if (!ipOnly.isEmpty() && !seenIps.contains(ipOnly) && !ipOnly.equals("127.0.0.1") && !ipOnly.equals("::1")) {
                        Map<String, String> map = new HashMap<>();
                        map.put("user", "system/ssh");
                        map.put("terminal", "tcp/raw");
                        map.put("loginTime", "ACTIVE TCP");
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

    @GetMapping("/voltage")
    public Map<String, String> getVoltage() {
        // Dùng sensors text output — frontend tự parse; fallback N/A nếu sensors không cài
        String cmd = "if hash sensors 2>/dev/null; then sensors 2>/dev/null; else echo 'N/A'; fi";
        String result = sshService.executeCommand(cmd);
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
        String cmd = "docker logs --tail " + clampedLines + " " + containerId + " 2>&1";
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