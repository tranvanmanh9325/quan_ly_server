package com.miniserver.dashboard.config;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class LoginRateLimiterTest {

    private LoginRateLimiter limiter;

    @BeforeEach
    void setUp() {
        limiter = new LoginRateLimiter();
    }

    @Test
    @DisplayName("should allow attempts below the max threshold")
    void testAllowsUnderLimit() {
        for (int i = 0; i < LoginRateLimiter.MAX_ATTEMPTS; i++) {
            assertTrue(limiter.tryConsume("1.2.3.4"),
                    "Attempt " + (i + 1) + " should be allowed");
        }
    }

    @Test
    @DisplayName("should block the attempt that exceeds the max threshold")
    void testBlocksOnLimitExceeded() {
        for (int i = 0; i < LoginRateLimiter.MAX_ATTEMPTS; i++) {
            limiter.tryConsume("1.2.3.4");
        }
        assertFalse(limiter.tryConsume("1.2.3.4"), "6th attempt should be blocked");
    }

    @Test
    @DisplayName("should isolate rate limits per IP — one IP blocked does not affect another")
    void testPerIpIsolation() {
        for (int i = 0; i < LoginRateLimiter.MAX_ATTEMPTS; i++) {
            limiter.tryConsume("10.0.0.1");
        }
        // 10.0.0.1 is now blocked, but 10.0.0.2 should still be allowed
        assertTrue(limiter.tryConsume("10.0.0.2"), "Different IP should not be rate limited");
    }

    @Test
    @DisplayName("retryAfterSeconds returns 0 for an IP that has not hit the limit")
    void testRetryAfterSeconds_NotBlocked() {
        limiter.tryConsume("5.6.7.8");
        assertEquals(0, limiter.retryAfterSeconds("5.6.7.8"));
    }

    @Test
    @DisplayName("retryAfterSeconds returns a positive value for a blocked IP")
    void testRetryAfterSeconds_Blocked() {
        for (int i = 0; i < LoginRateLimiter.MAX_ATTEMPTS; i++) {
            limiter.tryConsume("9.9.9.9");
        }
        assertTrue(limiter.retryAfterSeconds("9.9.9.9") > 0,
                "retryAfterSeconds should be positive when IP is blocked");
    }

    @Test
    @DisplayName("retryAfterSeconds returns 0 for an unknown IP")
    void testRetryAfterSeconds_UnknownIp() {
        assertEquals(0, limiter.retryAfterSeconds("192.168.0.1"));
    }
}
