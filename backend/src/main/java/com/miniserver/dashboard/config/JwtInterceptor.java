package com.miniserver.dashboard.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.miniserver.dashboard.service.JwtService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.Map;

/**
 * Validates JWT on every request to /api/** except /api/auth/**.
 * Returns 401 if the token is missing, malformed, or expired.
 * OPTIONS requests are always allowed (CORS preflight).
 */
@Component
public class JwtInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger(JwtInterceptor.class);

    private final JwtService jwtService;
    // ObjectMapper is thread-safe after construction; reuse to avoid allocation overhead.
    private final ObjectMapper objectMapper = new ObjectMapper();

    public JwtInterceptor(JwtService jwtService) {
        this.jwtService = jwtService;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        // Always permit CORS preflight
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }

        String authHeader = request.getHeader("Authorization");
        if (authHeader == null || !authHeader.startsWith("Bearer ")) {
            sendUnauthorized(response, "Missing or malformed Authorization header");
            return false;
        }

        String token = authHeader.substring(7); // strip "Bearer "
        if (!jwtService.validateToken(token)) {
            // Log to help detect brute-force or token-replay attacks
            log.warn("[JwtInterceptor] Invalid/expired token from IP: {} — {}",
                    request.getRemoteAddr(), request.getRequestURI());
            sendUnauthorized(response, "Token is invalid or expired");
            return false;
        }

        return true;
    }

    /**
     * Writes a JSON 401 response using Jackson to guarantee properly escaped output.
     * Never use string concatenation for JSON — any special char in `message` would
     * produce malformed JSON or open an injection vector.
     */
    private void sendUnauthorized(HttpServletResponse response, String message) throws Exception {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write(objectMapper.writeValueAsString(Map.of("error", message)));
    }
}

