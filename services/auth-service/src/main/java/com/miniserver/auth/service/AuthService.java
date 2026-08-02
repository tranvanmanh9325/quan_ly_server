package com.miniserver.auth.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Service
public class AuthService {

    private final String configuredUsername;
    private final String hashedPassword;
    private final JwtService jwtService;
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

    public String login(String username, String password) {
        boolean usernameMatch = safeEquals(configuredUsername, username);
        boolean passwordMatch = encoder.matches(password != null ? password : "", hashedPassword);
        if (!usernameMatch || !passwordMatch) {
            throw new IllegalArgumentException("Invalid credentials");
        }
        return jwtService.generateToken(username);
    }

    private boolean safeEquals(String expected, String actual) {
        byte[] a = expected.getBytes(StandardCharsets.UTF_8);
        byte[] b = (actual != null ? actual : "").getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(a, b);
    }
}
