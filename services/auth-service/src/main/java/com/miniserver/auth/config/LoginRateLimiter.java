package com.miniserver.auth.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class LoginRateLimiter {

    private static final Logger log = LoggerFactory.getLogger(LoginRateLimiter.class);

    static final int MAX_ATTEMPTS = 5;
    static final long WINDOW_MS = 60_000L;

    private final Map<String, Deque<Long>> attempts = new ConcurrentHashMap<>();

    public boolean tryConsume(String ip) {
        long now = System.currentTimeMillis();
        Deque<Long> window = attempts.computeIfAbsent(ip, k -> new ArrayDeque<>());

        synchronized (window) {
            while (!window.isEmpty() && now - window.peekFirst() > WINDOW_MS) {
                window.pollFirst();
            }

            if (window.size() >= MAX_ATTEMPTS) {
                long oldestMs = window.peekFirst();
                long retryAfterS = (WINDOW_MS - (now - oldestMs)) / 1000 + 1;
                log.warn("[LoginRateLimiter] Rate limit exceeded for IP: {} — retry in {}s", ip, retryAfterS);
                return false;
            }

            window.addLast(now);
            return true;
        }
    }

    public long retryAfterSeconds(String ip) {
        long now = System.currentTimeMillis();
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
