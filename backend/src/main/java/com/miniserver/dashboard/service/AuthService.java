package com.miniserver.dashboard.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Service
public class AuthService {

    private final String configuredUsername;
    // Stored as a BCrypt hash — never the raw password.
    private final String hashedPassword;
    private final JwtService jwtService;

    // BCryptPasswordEncoder is thread-safe; cost factor 12 is OWASP-recommended minimum.
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder(12);

    public AuthService(
            @Value("${app.auth.username}") String username,
            @Value("${app.auth.password}") String hashedPassword,
            JwtService jwtService
    ) {
        this.configuredUsername = username;
        this.hashedPassword = hashedPassword;
        this.jwtService = jwtService;
    }

    /**
     * Validates credentials and returns a JWT token on success.
     * Throws IllegalArgumentException if credentials are invalid —
     * caller (AuthController) maps this to HTTP 401.
     *
     * Username uses MessageDigest.isEqual() for constant-time comparison.
     * Password uses BCryptPasswordEncoder.matches() which is inherently timing-safe
     * (bcrypt always runs the full KDF regardless of where strings diverge).
     * Both checks are evaluated unconditionally before branching.
     */
    public String login(String username, String password) {
        boolean usernameMatch = safeEquals(configuredUsername, username);
        // BCrypt.matches() is inherently constant-time — always runs the full hash
        boolean passwordMatch = encoder.matches(password != null ? password : "", hashedPassword);
        // Evaluate both before branching — avoids short-circuit timing leak
        if (!usernameMatch || !passwordMatch) {
            throw new IllegalArgumentException("Invalid credentials");
        }
        return jwtService.generateToken(username);
    }

    /**
     * Constant-time string comparison backed by MessageDigest.isEqual().
     * Takes the same wall-clock time regardless of where strings diverge.
     */
    private boolean safeEquals(String expected, String actual) {
        byte[] a = expected.getBytes(StandardCharsets.UTF_8);
        byte[] b = (actual != null ? actual : "").getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(a, b);
    }
}
