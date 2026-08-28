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
 *   1. ClientTrackingFilter.recordAccess(ip)                  — passive, IP-only
 *   2. recordCheckin(ip, lat, lon, city, isp, country, cc)    — active, full geo from browser
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
            String country,
            String countryCode,
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
     * Only updates timestamp if existing entry already has geo data from a checkin,
     * so precise coordinates are never overwritten by passive tracking.
     */
    public void recordAccess(String ip) {
        clients.compute(ip, (k, existing) -> {
            if (existing != null && existing.hasGeo()) {
                // Refresh TTL, preserve all geo fields
                return new ClientEntry(ip, existing.lat(), existing.lon(),
                        existing.city(), existing.isp(),
                        existing.country(), existing.countryCode(),
                        System.currentTimeMillis());
            }
            return new ClientEntry(ip, 0.0, 0.0, null, null, null, null,
                    System.currentTimeMillis());
        });
    }

    /**
     * Called by the /client-checkin endpoint with precise browser-reported geo.
     * IP is always extracted server-side — never trusted from client body.
     */
    public void recordCheckin(String ip, double lat, double lon,
                              String city, String isp,
                              String country, String countryCode) {
        clients.put(ip, new ClientEntry(
                ip, lat, lon,
                city        != null ? city        : "Unknown",
                isp         != null ? isp         : "Browser",
                country     != null ? country     : "Unknown",
                countryCode != null ? countryCode : "UN",
                System.currentTimeMillis()
        ));
    }

    /**
     * Returns a snapshot of active clients, pruning expired entries first.
     * Shape matches MetricsController.getConnections() output with extra geo fields
     * when the client has done a checkin.
     */
    public List<Map<String, String>> getActiveClients() {
        clients.entrySet().removeIf(e -> e.getValue().isExpired());

        List<Map<String, String>> result = new ArrayList<>();
        for (ClientEntry entry : clients.values()) {
            Map<String, String> m = new HashMap<>();
            m.put("ip",        entry.ip());
            m.put("user",      "browser");
            m.put("terminal",  "HTTP/HTTPS");
            m.put("loginTime", "VIEWING");
            if (entry.hasGeo()) {
                m.put("lat",         String.valueOf(entry.lat()));
                m.put("lon",         String.valueOf(entry.lon()));
                m.put("city",        entry.city());
                m.put("isp",         entry.isp());
                m.put("country",     entry.country());
                m.put("countryCode", entry.countryCode());
            }
            result.add(m);
        }
        return result;
    }
}
