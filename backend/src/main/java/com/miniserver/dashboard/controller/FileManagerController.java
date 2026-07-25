package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.service.SshService;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
@RequestMapping("/api/files")
public class FileManagerController {

    private final SshService sshService;

    public FileManagerController(SshService sshService) {
        this.sshService = sshService;
    }

    private static final List<String> RESTRICTED_PATHS = List.of(
        "/etc/shadow", "/etc/sudoers", "/root/.ssh", "/etc/gshadow"
    );

    @GetMapping("/list")
    public Map<String, Object> listDirectory(@RequestParam(defaultValue = "/") String path) {
        Map<String, Object> response = new HashMap<>();
        String normalizedPath = normalizePosixPath(path);

        if (isRestrictedPath(normalizedPath)) {
            response.put("status", "error");
            response.put("message", "Access denied: Restricted system path");
            return response;
        }

        String cmd = "ls -la --time-style=long-iso " + escapeShellArg(normalizedPath);
        String raw = sshService.executeCommand(cmd);

        if (raw == null || raw.isBlank() || raw.startsWith("ERROR")) {
            response.put("status", "error");
            response.put("message", "Unable to list directory: " + (raw != null ? raw : "Empty output"));
            return response;
        }

        List<Map<String, String>> files = new ArrayList<>();
        String[] lines = raw.trim().split("\n");
        for (String line : lines) {
            String trimmed = line.trim();
            if (trimmed.startsWith("total") || trimmed.isEmpty()) continue;

            String[] parts = trimmed.split("\\s+", 8);
            if (parts.length >= 8) {
                Map<String, String> fileInfo = new HashMap<>();
                fileInfo.put("permissions", parts[0]);
                fileInfo.put("links", parts[1]);
                fileInfo.put("owner", parts[2]);
                fileInfo.put("group", parts[3]);
                fileInfo.put("size", parts[4]);
                fileInfo.put("date", parts[5] + " " + parts[6]);
                fileInfo.put("name", parts[7]);
                fileInfo.put("isDir", String.valueOf(parts[0].startsWith("d")));
                files.add(fileInfo);
            }
        }

        response.put("status", "success");
        response.put("path", normalizedPath);
        response.put("files", files);
        return response;
    }

    @GetMapping("/read")
    public Map<String, String> readFile(@RequestParam String path, @RequestParam(defaultValue = "100") int lines) {
        Map<String, String> response = new HashMap<>();
        String normalizedPath = normalizePosixPath(path);

        if (isRestrictedPath(normalizedPath)) {
            response.put("status", "error");
            response.put("data", "Access denied: Restricted sensitive file");
            return response;
        }

        int clampedLines = Math.max(10, Math.min(lines, 1000));
        String cmd = "tail -n " + clampedLines + " " + escapeShellArg(normalizedPath);
        String res = sshService.executeCommand(cmd);

        response.put("status", "success");
        response.put("path", normalizedPath);
        response.put("data", res != null ? res.trim() : "");
        return response;
    }

    /**
     * Cross-platform POSIX path normalizer independent of Host OS FileSystem.
     * Prevents Path Traversal attempts using '..' or redundant slashes.
     */
    private String normalizePosixPath(String input) {
        if (input == null || input.isBlank()) return "/";
        String clean = input.trim().replaceAll("[;&|`$]", "");
        String[] segments = clean.split("/+");
        Deque<String> stack = new ArrayDeque<>();
        for (String seg : segments) {
            if ("..".equals(seg)) {
                if (!stack.isEmpty()) {
                    stack.pop();
                }
            } else if (!".".equals(seg) && !seg.isEmpty()) {
                stack.push(seg);
            }
        }
        List<String> list = new ArrayList<>(stack);
        Collections.reverse(list);
        return "/" + String.join("/", list);
    }

    private boolean isRestrictedPath(String normalizedPath) {
        if (normalizedPath == null || normalizedPath.isBlank()) return false;
        String lowerPath = normalizedPath.toLowerCase();
        boolean directRestricted = RESTRICTED_PATHS.stream().anyMatch(restricted -> {
            String normRestricted = restricted.toLowerCase();
            return lowerPath.equals(normRestricted) || lowerPath.startsWith(normRestricted + "/");
        });
        if (directRestricted) return true;

        String realPath = resolveRemoteRealPath(normalizedPath);
        if (realPath != null && !realPath.equalsIgnoreCase(normalizedPath)) {
            String lowerRealPath = realPath.toLowerCase();
            return RESTRICTED_PATHS.stream().anyMatch(restricted -> {
                String normRestricted = restricted.toLowerCase();
                return lowerRealPath.equals(normRestricted) || lowerRealPath.startsWith(normRestricted + "/");
            });
        }
        return false;
    }

    private String resolveRemoteRealPath(String path) {
        String cmd = "realpath -m " + escapeShellArg(path) + " 2>/dev/null";
        String res = sshService.executeCommand(cmd);
        if (res != null && !res.isBlank() && !res.startsWith("ERROR") && !res.startsWith("Lỗi SSH")) {
            return res.trim();
        }
        return path;
    }

    private String escapeShellArg(String arg) {
        return "'" + arg.replace("'", "'\\''") + "'";
    }
}
