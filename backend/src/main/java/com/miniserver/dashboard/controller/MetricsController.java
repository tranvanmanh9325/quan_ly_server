package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.service.SshService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/metrics")
public class MetricsController {

    private final SshService sshService;

    public MetricsController(SshService sshService) {
        this.sshService = sshService;
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

    @GetMapping("/cpu")
    public Map<String, String> getCpu() {
        return safeData(sshService.executeCommand("top -b -n 1 | grep 'Cpu(s)'"));
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
        String result = sshService.executeCommand("who");
        List<Map<String, String>> connections = new ArrayList<>();
        if (result != null && !result.isBlank()) {
            String[] lines = result.trim().split("\n");
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
}