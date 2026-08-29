package com.miniserver.auth.service;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Date;

@Service
public class JwtService {

    private final SecretKey secretKey;
    private final long expirationMs;
    private final JwtParser prebuiltParser;

    // In-memory Caffeine cache for verified claims (avoids re-running HMAC SHA-256 on every request)
    private final Cache<String, Claims> tokenClaimsCache = Caffeine.newBuilder()
            .maximumSize(10_000)
            .expireAfterWrite(Duration.ofMinutes(5))
            .build();

    public JwtService(
            @Value("${app.jwt.secret}") String secret,
            @Value("${app.jwt.expiration-hours}") int expirationHours
    ) {
        this.secretKey = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        this.expirationMs = (long) expirationHours * 3600 * 1000L;
        // Pre-build immutable thread-safe parser instance once at startup
        this.prebuiltParser = Jwts.parser()
                .verifyWith(this.secretKey)
                .build();
    }

    public String generateToken(String username) {
        Date now = new Date();
        return Jwts.builder()
                .subject(username)
                .issuedAt(now)
                .expiration(new Date(now.getTime() + expirationMs))
                .signWith(secretKey)
                .compact();
    }

    public String extractUsername(String token) {
        Claims claims = parseClaimsWithCache(token);
        return claims != null ? claims.getSubject() : null;
    }

    public boolean validateToken(String token) {
        Claims claims = parseClaimsWithCache(token);
        return claims != null && claims.getExpiration().after(new Date());
    }

    private Claims parseClaimsWithCache(String token) {
        if (token == null || token.isBlank()) return null;
        try {
            return tokenClaimsCache.get(token, k -> prebuiltParser.parseSignedClaims(k).getPayload());
        } catch (JwtException | IllegalArgumentException e) {
            return null;
        }
    }
}
