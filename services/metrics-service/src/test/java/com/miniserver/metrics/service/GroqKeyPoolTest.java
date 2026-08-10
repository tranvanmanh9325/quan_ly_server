package com.miniserver.metrics.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for GroqKeyPool — verifies 9router-style behavior:
 *   1. Round-Robin: each request uses the next key in cycle, no key skipped.
 *   2. 429 Cooldown: rate-limited keys are excluded for 60s.
 *   3. Instant Failover: after a 429, next getNextKey() returns a healthy key immediately.
 *   4. Cooldown Recovery: expired cooldown keys re-enter the pool automatically.
 *   5. All-keys-on-cooldown: gracefully returns the soonest-expiring key instead of null.
 *
 * All tests are pure unit tests — no network, no SSH, no Spring context required.
 * Runs on every build including CI/CD.
 */
class GroqKeyPoolTest {

    private static final String K1 = "gsk_key_one_____test";
    private static final String K2 = "gsk_key_two_____test";
    private static final String K3 = "gsk_key_three___test";

    private GroqKeyPool pool3;

    @BeforeEach
    void setUp() {
        pool3 = new GroqKeyPool(K1, K2, K3, "", "");
    }

    // ─── hasKeys / getKeyCount ────────────────────────────────────────────────

    @Test
    @DisplayName("Empty pool: hasKeys=false, getKeyCount=0, getNextKey=null")
    void emptyPool() {
        GroqKeyPool empty = new GroqKeyPool("", "", "", "", "");
        assertFalse(empty.hasKeys(), "Empty pool must report no keys");
        assertEquals(0, empty.getKeyCount(), "Empty pool key count must be 0");
        assertNull(empty.getNextKey(), "Empty pool must return null from getNextKey()");
    }

    @Test
    @DisplayName("Pool with 3 keys: hasKeys=true, getKeyCount=3")
    void poolWith3Keys() {
        assertTrue(pool3.hasKeys());
        assertEquals(3, pool3.getKeyCount());
    }

    // ─── Round-Robin ──────────────────────────────────────────────────────────

    @Test
    @DisplayName("Round-robin: 6 calls with 3 keys must cycle K1→K2→K3→K1→K2→K3 (no gap)")
    void roundRobinStrictCycle() {
        // Collect 6 results sequentially
        List<String> results = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            results.add(pool3.getNextKey());
        }

        // First full cycle
        assertEquals(K1, results.get(0), "Call 1 → K1");
        assertEquals(K2, results.get(1), "Call 2 → K2");
        assertEquals(K3, results.get(2), "Call 3 → K3");
        // Second full cycle — pointer wraps correctly
        assertEquals(K1, results.get(3), "Call 4 → K1 (wrap)");
        assertEquals(K2, results.get(4), "Call 5 → K2 (wrap)");
        assertEquals(K3, results.get(5), "Call 6 → K3 (wrap)");
    }

    @Test
    @DisplayName("All 3 distinct keys appear in the first 3 calls (no duplicate before full cycle)")
    void firstCycleCoverAllKeys() {
        Set<String> seen = new HashSet<>();
        for (int i = 0; i < 3; i++) seen.add(pool3.getNextKey());
        assertEquals(Set.of(K1, K2, K3), seen, "Every key must appear exactly once in first cycle");
    }

    // ─── 429 Cooldown & Instant Failover ─────────────────────────────────────

    @Test
    @DisplayName("After markRateLimited, the key must NOT appear in any subsequent getNextKey() call")
    void rateLimitedKeyNeverReturned() {
        pool3.markRateLimited(K1);

        for (int i = 0; i < 12; i++) {
            String key = pool3.getNextKey();
            assertNotEquals(K1, key,
                    "Rate-limited K1 must never be returned (call " + (i + 1) + ")");
        }
    }

    @Test
    @DisplayName("Healthy keys still rotate normally when one is on cooldown")
    void healthyKeysStillRotateAfterCooldown() {
        pool3.markRateLimited(K2); // only K2 on cooldown

        Set<String> returned = new HashSet<>();
        for (int i = 0; i < 8; i++) returned.add(pool3.getNextKey());

        assertFalse(returned.contains(K2), "Cooldown K2 must never appear");
        assertTrue(returned.contains(K1), "K1 must still rotate");
        assertTrue(returned.contains(K3), "K3 must still rotate");
    }

    @Test
    @DisplayName("Instant failover: after K1 marked rate-limited, very next call returns a different key")
    void instantFailoverOnNextCall() {
        // Simulate: K1 was used, returned 429, now marked
        pool3.markRateLimited(K1);

        // Next call must NOT be K1
        String next = pool3.getNextKey();
        assertNotEquals(K1, next, "Instant failover: next key after 429 must not be K1");
        assertNotNull(next, "Instant failover must still return a key (not null)");
    }

    @Test
    @DisplayName("Simulate callGroq failover flow: K1 gets 429 → K2 succeeds — exactly like 9router")
    void simulateCallGroqFailoverFlow() {
        // Reproduce the exact sequence that happens inside callGroq() when K1 hits 429:
        //   attempt 0: getNextKey() → K1 → 429 → markRateLimited(K1)
        //   attempt 1: getNextKey() → should NOT be K1 → request succeeds
        String key0 = pool3.getNextKey(); // attempt 0: K1
        assertEquals(K1, key0, "First request should use K1 (first in rotation)");

        // K1 returned 429 — simulate what callGroq() does
        pool3.markRateLimited(key0);

        // attempt 1 inside callGroq() loop
        String key1 = pool3.getNextKey();
        assertNotEquals(K1, key1, "After K1 rate-limited, next getNextKey() must skip K1");
        assertNotNull(key1, "Failover must return a valid key");
    }

    @Test
    @DisplayName("Two keys in a row hit 429 → third key succeeds")
    void twoConsecutive429sFailoverToThird() {
        // K1 → 429 → mark K1
        String k = pool3.getNextKey();
        assertEquals(K1, k);
        pool3.markRateLimited(k);

        // K2 → 429 → mark K2
        k = pool3.getNextKey();
        assertEquals(K2, k, "Second attempt should be K2");
        pool3.markRateLimited(k);

        // K3 should now succeed (not K1 or K2)
        k = pool3.getNextKey();
        assertEquals(K3, k, "Third attempt should be K3 — the only healthy key");
    }

    // ─── Cooldown Recovery ────────────────────────────────────────────────────

    @Test
    @DisplayName("Key with expired cooldown automatically re-enters the pool")
    void expiredCooldownKeyRecovers() {
        // Inject an already-expired cooldown for K1 using reflection
        @SuppressWarnings("unchecked")
        ConcurrentHashMap<String, Instant> cooldowns =
                (ConcurrentHashMap<String, Instant>) ReflectionTestUtils.getField(pool3, "cooldowns");
        cooldowns.put(K1, Instant.now().minusSeconds(1)); // expired 1 second ago

        // K1 should appear in the next few calls
        boolean k1Recovered = false;
        for (int i = 0; i < 6; i++) {
            if (K1.equals(pool3.getNextKey())) {
                k1Recovered = true;
                break;
            }
        }
        assertTrue(k1Recovered, "K1 with expired cooldown must recover and be returned");
    }

    // ─── All-keys-on-cooldown fallback ────────────────────────────────────────

    @Test
    @DisplayName("When all keys on cooldown, return the soonest-expiring key (not null)")
    void allOnCooldownReturnsSoonestExpiring() {
        GroqKeyPool pool2 = new GroqKeyPool(K1, K2, "", "", "");

        @SuppressWarnings("unchecked")
        ConcurrentHashMap<String, Instant> cooldowns =
                (ConcurrentHashMap<String, Instant>) ReflectionTestUtils.getField(pool2, "cooldowns");

        // K1 expires in 30s (sooner), K2 expires in 55s (later)
        cooldowns.put(K1, Instant.now().plusSeconds(30));
        cooldowns.put(K2, Instant.now().plusSeconds(55));

        String result = pool2.getNextKey();
        assertNotNull(result, "Must never return null even when all keys on cooldown");
        assertEquals(K1, result, "Must return K1 — the key that expires soonest");
    }

    // ─── Pool Status ──────────────────────────────────────────────────────────

    @Test
    @DisplayName("getPoolStatus() accurately reflects healthy and cooldown keys")
    void poolStatusAccurate() {
        pool3.markRateLimited(K2);

        String status = pool3.getPoolStatus();

        assertNotNull(status);
        assertTrue(status.contains("3 key(s)"),       "Status must report 3 total keys");
        assertTrue(status.contains("key1: OK"),        "K1 must be OK");
        assertTrue(status.contains("key2: COOLDOWN"),  "K2 must be COOLDOWN");
        assertTrue(status.contains("key3: OK"),        "K3 must be OK");
    }

    @Test
    @DisplayName("Empty pool status returns 'No keys loaded.'")
    void emptyPoolStatus() {
        GroqKeyPool empty = new GroqKeyPool("", "", "", "", "");
        assertEquals("No keys loaded.", empty.getPoolStatus());
    }

    // ─── Edge cases ───────────────────────────────────────────────────────────

    @Test
    @DisplayName("markRateLimited with null or blank must not throw")
    void markRateLimitedNullSafe() {
        assertDoesNotThrow(() -> pool3.markRateLimited(null));
        assertDoesNotThrow(() -> pool3.markRateLimited(""));
        assertDoesNotThrow(() -> pool3.markRateLimited("   "));
        // Verify pool is still functional after edge-case inputs
        assertNotNull(pool3.getNextKey(), "Pool must still work after null/blank markRateLimited calls");
    }

    @Test
    @DisplayName("Single-key pool: getNextKey always returns the same key (no alternative)")
    void singleKeyPool() {
        GroqKeyPool pool1 = new GroqKeyPool(K1, "", "", "", "");
        for (int i = 0; i < 5; i++) {
            assertEquals(K1, pool1.getNextKey(), "Single-key pool must always return K1");
        }
    }

    @Test
    @DisplayName("Single-key pool on cooldown: still returns that key (best effort, no null)")
    void singleKeyOnCooldownNotNull() {
        GroqKeyPool pool1 = new GroqKeyPool(K1, "", "", "", "");
        pool1.markRateLimited(K1);

        // Even with the only key on cooldown, must return something
        assertNotNull(pool1.getNextKey(), "Must not return null even with single key on cooldown");
    }
}
