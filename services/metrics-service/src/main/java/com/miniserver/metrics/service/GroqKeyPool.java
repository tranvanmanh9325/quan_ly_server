package com.miniserver.metrics.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Thread-safe Groq API key pool implementing 9router-style rotation.
 *
 * Strategy:
 *   1. Round-Robin — distributes requests evenly across all available keys.
 *   2. Smart Cooldown — keys that hit 429 are excluded from the pool for
 *      COOLDOWN_SECONDS and then automatically reinstated.
 *   3. Instant Failover — if the selected key is on cooldown, the next
 *      available key is returned immediately without sleeping.
 *
 * All methods are thread-safe. Uses AtomicInteger + ConcurrentHashMap so
 * concurrent Telegram messages never race on key selection.
 */
@Service
public class GroqKeyPool {

    private static final Logger log = LoggerFactory.getLogger(GroqKeyPool.class);

    // Duration a key stays excluded from the pool after hitting a 429.
    private static final long COOLDOWN_SECONDS = 60L;

    /** Ordered, immutable list of API keys built once at startup. */
    private final List<String> keys;

    /** Rolling pointer for round-robin; wraps via modulo. */
    private final AtomicInteger pointer = new AtomicInteger(0);

    /**
     * Tracks the cooldown-expiry instant per key.
     * Absent entry means key is healthy and available.
     */
    private final ConcurrentHashMap<String, Instant> cooldowns = new ConcurrentHashMap<>();

    // ─── Constructor / key loading ────────────────────────────────────────────

    public GroqKeyPool(
            @Value("${groq.api-key:}")   String key1,
            @Value("${groq.api-key-2:}") String key2,
            @Value("${groq.api-key-3:}") String key3,
            @Value("${groq.api-key-4:}") String key4,
            @Value("${groq.api-key-5:}") String key5
    ) {
        List<String> loaded = new ArrayList<>();
        for (String k : List.of(key1, key2, key3, key4, key5)) {
            if (k != null && !k.isBlank()) {
                loaded.add(k.trim());
            }
        }
        this.keys = Collections.unmodifiableList(loaded);
        log.info("[GroqKeyPool] Loaded {} API key(s).", this.keys.size());
    }

    // ─── Public API ───────────────────────────────────────────────────────────

    /** Returns true if at least one key is loaded (ignores cooldown state). */
    public boolean hasKeys() {
        return !keys.isEmpty();
    }

    /** Returns the total number of configured keys (including keys on cooldown). */
    public int getKeyCount() {
        return keys.size();
    }


    /**
     * Returns the next available (non-cooldown) key using round-robin.
     * If ALL keys are currently on cooldown, returns the least-recently
     * rate-limited key (the one whose cooldown expires soonest) so the
     * caller can still attempt the request rather than failing hard.
     *
     * @return a Groq API key string, or null if no keys were loaded at all.
     */
    public String getNextKey() {
        if (keys.isEmpty()) return null;

        Instant now  = Instant.now();
        int     size = keys.size();

        // Try every key in round-robin order starting from the current pointer.
        for (int attempt = 0; attempt < size; attempt++) {
            int    idx       = Math.abs(pointer.getAndIncrement() % size);
            String candidate = keys.get(idx);

            Instant coolUntil = cooldowns.get(candidate);
            if (coolUntil == null || now.isAfter(coolUntil)) {
                // Key is healthy — remove any stale cooldown entry and use it.
                cooldowns.remove(candidate);
                return candidate;
            }
        }

        // All keys are on cooldown. Return the one that expires soonest so we
        // have the best chance of the request succeeding.
        log.warn("[GroqKeyPool] All {} key(s) on cooldown — using least-restricted key.", size);
        return keys.stream()
                .min((a, b) -> {
                    Instant ia = cooldowns.getOrDefault(a, Instant.EPOCH);
                    Instant ib = cooldowns.getOrDefault(b, Instant.EPOCH);
                    return ia.compareTo(ib);
                })
                .orElse(keys.get(0));
    }

    /**
     * Marks a key as rate-limited; excluded from rotation for COOLDOWN_SECONDS.
     * Safe to call multiple times for the same key.
     *
     * @param key the key that returned HTTP 429
     */
    public void markRateLimited(String key) {
        if (key == null || key.isBlank()) return;
        Instant expiry = Instant.now().plusSeconds(COOLDOWN_SECONDS);
        cooldowns.put(key, expiry);
        log.warn("[GroqKeyPool] Key ...{} rate-limited; excluded for {}s.",
                maskedSuffix(key), COOLDOWN_SECONDS);
    }

    /**
     * Human-readable pool status for logging/debugging.
     * Example: "3 keys total — key1: OK, key2: COOLDOWN(42s), key3: OK"
     */
    public String getPoolStatus() {
        if (keys.isEmpty()) return "No keys loaded.";
        Instant now = Instant.now();
        StringBuilder sb = new StringBuilder(keys.size() + " key(s) total — ");
        for (int i = 0; i < keys.size(); i++) {
            String  k         = keys.get(i);
            Instant coolUntil = cooldowns.get(k);
            if (coolUntil == null || now.isAfter(coolUntil)) {
                sb.append("key").append(i + 1).append(": OK");
            } else {
                long remaining = coolUntil.getEpochSecond() - now.getEpochSecond();
                sb.append("key").append(i + 1).append(": COOLDOWN(").append(remaining).append("s)");
            }
            if (i < keys.size() - 1) sb.append(", ");
        }
        return sb.toString();
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────

    /** Returns last 6 chars of a key for safe log output. */
    private static String maskedSuffix(String key) {
        return key.length() > 6 ? key.substring(key.length() - 6) : "***";
    }
}
