package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.service.SshService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
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
        String result = sshService.executeCommand("df -h /");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }

    @GetMapping("/processes")
    public Map<String, String> getProcesses() {
        // Lấy top 5 processes tốn CPU nhất
        String result = sshService.executeCommand("ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu | head -n 6");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }
    
    @GetMapping("/system")
    public Map<String, String> getSystemStatus() {
        String result = sshService.executeCommand("uptime");
        Map<String, String> map = new HashMap<>();
        map.put("data", result.trim());
        return map;
    }
}
