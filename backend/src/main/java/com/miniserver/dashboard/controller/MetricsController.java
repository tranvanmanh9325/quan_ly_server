package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.service.SshService;
import org.springframework.beans.factory.annotation.Autowired;
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

    @Autowired
    private SshService sshService;

    @GetMapping("/cpu")
    public Map<String, String> getCpu() {
        String result = sshService.executeCommand("top -b -n 1 | grep 'Cpu(s)'");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }

    @GetMapping("/ram")
    public Map<String, String> getRam() {
        String result = sshService.executeCommand("free -m");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }

    @GetMapping("/disk")
    public Map<String, String> getDisk() {
        String result = sshService.executeCommand("df -h -x tmpfs -x devtmpfs");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }

    @GetMapping("/network")
    public Map<String, String> getNetwork() {
        String result = sshService.executeCommand("cat /proc/net/dev");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }

    @GetMapping("/processes")
    public Map<String, String> getProcesses() {
        // Lấy toàn bộ processes thay vì top 5, bổ sung nlwp (threads), rss (dung lượng RAM bằng KB) và args (lệnh đầy đủ)
        String result = sshService.executeCommand("ps -eo pid,user,%cpu,%mem,nlwp,rss,args --sort=-%cpu");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }

    @GetMapping("/temperature")
    public Map<String, String> getTemperature() {
        // Gộp check hwmon và thermal_zone để loại bỏ cảm biến ACPI ảo bị kẹt cứng ở 25000
        String cmd = "t=\"\"; if hash sensors 2>/dev/null; then t=$(sensors | awk '/[Cc]ore|[Pp]ackage|[Tt]die|[Tt]ctl/ {match($0, /[0-9.]+/); print int(substr($0, RSTART, RLENGTH) * 1000); exit}'); fi; " +
                     "if [ -n \"$t\" ]; then echo \"$t\"; else " +
                     "cat /sys/class/hwmon/hwmon*/temp*_input /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk '{if($1 != 25000 && $1 != 26800 && $1 > 0 && $1 < 120000) print $1}' | head -n 1; fi";

        String result = sshService.executeCommand(cmd);
        Map<String, String> map = new HashMap<>();
        map.put("data", (result != null && !result.trim().isEmpty()) ? result.trim() : "N/A");
        return map;
    }

    @GetMapping("/system")
    public Map<String, String> getSystemStatus() {
        String result = sshService.executeCommand("uptime");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }

    @GetMapping("/connections")
    public Map<String, Object> getConnections() {
        String result = sshService.executeCommand("who");
        List<Map<String, String>> connections = new ArrayList<>();
        if (result != null && !result.trim().isEmpty()) {
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
        map.put("data", (result != null && !result.trim().isEmpty()) ? result.trim() : "N/A");
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

        if (raw != null && !raw.trim().isEmpty()) {
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
