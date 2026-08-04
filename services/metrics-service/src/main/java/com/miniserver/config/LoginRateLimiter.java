package com.miniserver.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * IP-based sliding-window rate limiter for the login endpoint.
 *
 * Algorithm: for each IP, maintain a deque of attempt timestamps.
 * On every request, evict timestamps older than the window, then check
 * whether the attempt count has reached the cap. No background thread
 * is needed — stale entries are lazily evicted on the next request from
 * the same IP, keeping memory bounded without a scheduler.
 *
 * Defaults: 5 attempts per 60-second window → blocks the 6th attempt
 * with HTTP 429 until the oldest attempt ages out of the window.
 */
@Component
public class LoginRateLimiter {

    private static final Logger log = LoggerFactory.getLogger(LoginRateLimiter.class);

    /** Maximum login attempts allowed within the time window. */
    static final int MAX_ATTEMPTS = 5;

    /** Sliding window duration in milliseconds (60 seconds). */
    static final long WINDOW_MS = 60_000L;

    // ConcurrentHashMap for thread-safe per-IP tracking.
    // ArrayDeque is not thread-safe itself, but all accesses are
    // serialized through computeIfAbsent + synchronized(deque) below.
    private final Map<String, Deque<Long>> attempts = new ConcurrentHashMap<>();

    /**
     * Returns true if the IP is allowed to attempt a login.
     * Records the attempt timestamp if allowed; does nothing if blocked.
     *
     * @param ip  client IP address (from HttpServletRequest.getRemoteAddr())
     */
    public boolean tryConsume(String ip) {
        long now = System.currentTimeMillis();

        Deque<Long> window = attempts.computeIfAbsent(ip, k -> new ArrayDeque<>());

        synchronized (window) {
            // Evict timestamps that have slid out of the window
            while (!window.isEmpty() && now - window.peekFirst() > WINDOW_MS) {
                window.pollFirst();
            }

            if (window.size() >= MAX_ATTEMPTS) {
                long oldestMs    = window.peekFirst();
                long retryAfterS = (WINDOW_MS - (now - oldestMs)) / 1000 + 1;
                log.warn("[LoginRateLimiter] Rate limit exceeded for IP: {} — retry in {}s", ip, retryAfterS);
                return false;
            }

            window.addLast(now);
            return true;
        }
    }

    /**
     * Returns how many seconds until the rate limit resets for a given IP.
     * Returns 0 if the IP is not currently blocked.
     */
    public long retryAfterSeconds(String ip) {
        long now    = System.currentTimeMillis();
        Deque<Long> window = attempts.get(ip);
        if (window == null) return 0;

        synchronized (window) {
            if (window.size() < MAX_ATTEMPTS) return 0;
            long oldestMs = window.peekFirst();
            long remaining = WINDOW_MS - (now - oldestMs);
            return remaining > 0 ? remaining / 1000 + 1 : 0;
        }
    }
}
