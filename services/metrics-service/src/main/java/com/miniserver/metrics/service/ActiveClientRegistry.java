package com.miniserver.metrics.service;

import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Thread-safe in-memory registry of active HTTP clients.
 *
 * Two registration paths:
 *   1. ClientTrackingFilter.recordAccess(ip)   — passive, IP-only, from proxy headers
 *   2. recordCheckin(ip, lat, lon, city, isp)  — active, full geo from browser self-report
 *
 * Active checkins (path 2) override passive entries so the map always shows
 * the most precise location available. Entries expire after 5 minutes.
 */
@Service
public class ActiveClientRegistry {

    private static final long CLIENT_TTL_MS = 5 * 60 * 1000L; // 5 minutes

    private record ClientEntry(
            String ip,
            double lat,
            double lon,
            String city,
            String isp,
            long lastSeenMs
    ) {
        boolean isExpired() {
            return System.currentTimeMillis() - lastSeenMs > CLIENT_TTL_MS;
        }
        boolean hasGeo() {
            return lat != 0.0 || lon != 0.0;
        }
    }

    private final ConcurrentHashMap<String, ClientEntry> clients = new ConcurrentHashMap<>();

    /**
     * Called by ClientTrackingFilter on every inbound HTTP request.
     * Only updates if no existing entry or existing entry has no geo data,
     * so active checkins are not overwritten by passive tracking.
     */
    public void recordAccess(String ip) {
        clients.compute(ip, (k, existing) -> {
            // Preserve geo data if already present from a checkin
            if (existing != null && existing.hasGeo()) {
                return new ClientEntry(ip, existing.lat(), existing.lon(),
                        existing.city(), existing.isp(), System.currentTimeMillis());
            }
            return new ClientEntry(ip, 0.0, 0.0, null, null, System.currentTimeMillis());
        });
    }

    /**
     * Called by the /client-checkin endpoint with precise browser-reported geo.
     * This is the most accurate source: browser GPS or network geolocation.
     */
    public void recordCheckin(String ip, double lat, double lon, String city, String isp) {
        clients.put(ip, new ClientEntry(ip, lat, lon,
                city != null ? city : "Unknown",
                isp != null ? isp : "Browser",
                System.currentTimeMillis()));
    }

    /**
     * Returns a snapshot of active clients, pruning expired entries first.
     * Shape matches MetricsController.getConnections() output, with extra geo fields
     * for entries that have done a checkin (lat/lon will override ip-api lookup downstream).
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
            // Include geo data if available — MetricsController will use these
            // instead of calling ip-api for this client
            if (entry.hasGeo()) {
                m.put("lat",  String.valueOf(entry.lat()));
                m.put("lon",  String.valueOf(entry.lon()));
                m.put("city", entry.city());
                m.put("isp",  entry.isp());
                m.put("country",     "Vietnam");  // Will be overridden by reverse-geo if needed
                m.put("countryCode", "VN");
            }
            result.add(m);
        }
        return result;
    }
}
