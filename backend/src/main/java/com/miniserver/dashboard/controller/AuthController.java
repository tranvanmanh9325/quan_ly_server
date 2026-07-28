package com.miniserver.dashboard.controller;

import com.miniserver.dashboard.config.LoginRateLimiter;
import com.miniserver.dashboard.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;
    private final LoginRateLimiter rateLimiter;

    public AuthController(AuthService authService, LoginRateLimiter rateLimiter) {
        this.authService = authService;
        this.rateLimiter = rateLimiter;
    }

    /**
     * POST /api/auth/login
     * Body: { "username": "...", "password": "..." }
     * Returns: { "token": "eyJ..." } on success.
     * Returns HTTP 429 with Retry-After header if the IP has exceeded
     * 5 attempts within the last 60 seconds.
     * Returns HTTP 401 on invalid credentials.
     */
    @PostMapping("/login")
    public ResponseEntity<Map<String, String>> login(
            @RequestBody Map<String, String> body,
            HttpServletRequest request
    ) {
        // Resolve real client IP: honour X-Forwarded-For if behind a reverse proxy
        String clientIp = resolveClientIp(request);

        if (!rateLimiter.tryConsume(clientIp)) {
            long retryAfter = rateLimiter.retryAfterSeconds(clientIp);
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                    .header(HttpHeaders.RETRY_AFTER, String.valueOf(retryAfter))
                    .body(Map.of("error", "Too many login attempts. Retry after " + retryAfter + "s."));
        }

        try {
            String token = authService.login(
                    body.getOrDefault("username", ""),
                    body.getOrDefault("password", "")
            );
            return ResponseEntity.ok(Map.of("token", token));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(Map.of("error", "Invalid credentials"));
        }
    }

    /**
     * POST /api/auth/logout — stateless JWT: just acknowledge.
     * Token removal is handled client-side (remove from localStorage).
     */
    @PostMapping("/logout")
    public ResponseEntity<Map<String, String>> logout() {
        return ResponseEntity.ok(Map.of("message", "Logged out"));
    }

    /**
     * Extracts the real client IP, checking X-Forwarded-For first.
     * Only trusts the first IP in the chain to prevent header injection.
     * Falls back to getRemoteAddr() when no proxy header is present.
     */
    private String resolveClientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            // X-Forwarded-For: client, proxy1, proxy2 — take only the first
            return forwarded.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
