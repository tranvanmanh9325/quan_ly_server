package com.miniserver.metrics.service;

import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Thread-safe in-memory registry of active HTTP clients.
 * Each request goes through ClientTrackingFilter which calls recordAccess().
 * Entries expire after CLIENT_TTL_MS (5 minutes) of inactivity.
 */
@Service
public class ActiveClientRegistry {

    private static final long CLIENT_TTL_MS = 5 * 60 * 1000L; // 5 minutes

    private record ClientEntry(String ip, long lastSeenMs) {
        boolean isExpired() {
            return System.currentTimeMillis() - lastSeenMs > CLIENT_TTL_MS;
        }
    }

    private final ConcurrentHashMap<String, ClientEntry> clients = new ConcurrentHashMap<>();

    /** Called by ClientTrackingFilter on every inbound HTTP request. */
    public void recordAccess(String ip) {
        clients.put(ip, new ClientEntry(ip, System.currentTimeMillis()));
    }

    /**
     * Returns a snapshot of active clients, pruning expired entries first.
     * Each map has: ip, user, terminal, loginTime — matches the shape
     * that MetricsController.getConnections() already produces.
     */
    public List<Map<String, String>> getActiveClients() {
        // Prune expired entries in-place (ConcurrentHashMap is safe for this)
        clients.entrySet().removeIf(e -> e.getValue().isExpired());

        List<Map<String, String>> result = new ArrayList<>();
        for (ClientEntry entry : clients.values()) {
            Map<String, String> m = new HashMap<>();
            m.put("ip",        entry.ip());
            m.put("user",      "browser");
            m.put("terminal",  "HTTP/HTTPS");
            m.put("loginTime", "VIEWING");
            result.add(m);
        }
        return result;
    }
}
