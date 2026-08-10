package com.miniserver.metrics.service;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Integration test for AiChatService — requires live SSH + Groq API credentials.
 *
 * This test is intentionally skipped (via Assumptions) when the required env vars
 * are absent, so it never blocks CI/CD pipelines that lack real server access.
 * To run locally: set SSH_HOST, SSH_USER, SSH_PASSWORD, GROQ_API_KEY env vars.
 */
class AiChatServiceTest {

    @Test
    void testChatAptUpdateTime() {
        // Skip gracefully on CI/CD — do NOT fail when env vars are absent
        Assumptions.assumeTrue(System.getenv("SSH_HOST") != null && !System.getenv("SSH_HOST").isBlank(),
                "Skipping integration test: SSH_HOST env var not set");
        Assumptions.assumeTrue(System.getenv("GROQ_API_KEY") != null && !System.getenv("GROQ_API_KEY").isBlank(),
                "Skipping integration test: GROQ_API_KEY env var not set");

        SshService sshService = new SshService();
        ReflectionTestUtils.setField(sshService, "host",         System.getenv("SSH_HOST"));
        ReflectionTestUtils.setField(sshService, "port",         Integer.parseInt(System.getenv().getOrDefault("SSH_PORT", "22")));
        ReflectionTestUtils.setField(sshService, "user",         System.getenv("SSH_USER"));
        ReflectionTestUtils.setField(sshService, "password",     System.getenv("SSH_PASSWORD"));
        ReflectionTestUtils.setField(sshService, "strictHostKeyChecking", "no");
        ReflectionTestUtils.setField(sshService, "fallbackHost", System.getenv().getOrDefault("SSH_FALLBACK_HOST", ""));
        ReflectionTestUtils.setField(sshService, "fallbackPort", Integer.parseInt(System.getenv().getOrDefault("SSH_FALLBACK_PORT", "22")));

        // Build GroqKeyPool with the primary key; pass empty strings for unused slots
        String groqKey = System.getenv("GROQ_API_KEY");
        GroqKeyPool keyPool = new GroqKeyPool(groqKey, "", "", "", "");

        AiChatService aiChatService = new AiChatService(sshService, keyPool);
        ReflectionTestUtils.setField(aiChatService, "model", "llama-3.1-8b-instant");

        String response = aiChatService.chat("test-chat-id", "Đã được cập nhật vào thời gian nào");
        System.out.println("=== AI RESPONSE START ===");
        System.out.println(response);
        System.out.println("=== AI RESPONSE END ===");

        assertNotNull(response);

        // Assert no error messages appear (Vietnamese error strings with diacritics)
        assertFalse(response.contains("quá tải"),      "Should not be rate limited");
        assertFalse(response.contains("không hợp lệ"), "Should not be invalid request");
        assertFalse(response.contains("xảy ra lỗi"),   "Should not return generic error");

        // Assert that the AI actually answered the question about apt update time,
        // not just returned an empty or off-topic response.
        // LLM output is non-deterministic, so we check for common date/time indicators.
        boolean containsTimeInfo = response.matches("(?si).*(\\d{2}/\\d{2}/\\d{4}|\\d{4}-\\d{2}-\\d{2}|tháng|ngày|giờ|update|upgrade|apt|\\d{2}:\\d{2}).*");
        assertTrue(containsTimeInfo, "Response should contain date/time information about the last update. Got: " + response);
    }
}
