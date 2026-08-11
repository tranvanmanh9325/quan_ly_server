package com.miniserver.metrics.filter;

import com.miniserver.metrics.service.ActiveClientRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.regex.Pattern;

/**
 * Intercepts every inbound HTTP request and records the real client IP
 * into ActiveClientRegistry, enabling the Global Map to show live browser
 * sessions without relying on `ss` socket stats (which cannot see through
 * Docker NAT or ngrok tunnels).
 *
 * IP extraction order:
 *   1. First entry of X-Forwarded-For (set by ngrok, Cloudflare, etc.)
 *   2. X-Real-IP (set by nginx proxy_set_header X-Real-IP $remote_addr)
 *   3. Servlet remote address (direct connections, fallback)
 *
 * Only routable, non-loopback, non-Docker-bridge IPs are stored.
 * LAN IPs (192.168.x.x, 10.x.x.x) ARE tracked — they appear on the
 * map pinned at the server's coordinates.
 */
@Component
public class ClientTrackingFilter extends OncePerRequestFilter {

    private static final Pattern IPV4_PATTERN =
            Pattern.compile("^(\\d{1,3}\\.){3}\\d{1,3}$");

    private final ActiveClientRegistry clientRegistry;

    public ClientTrackingFilter(ActiveClientRegistry clientRegistry) {
        this.clientRegistry = clientRegistry;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain)
            throws ServletException, IOException {
        String uri = request.getRequestURI();
        // Ignore health checks & static assets
        if (uri != null && (uri.contains("/actuator") || uri.contains("/health"))) {
            chain.doFilter(request, response);
            return;
        }

        String userAgent = request.getHeader("User-Agent");
        boolean isBrowser = userAgent != null && (
                userAgent.contains("Mozilla") || userAgent.contains("Chrome") ||
                userAgent.contains("Safari")  || userAgent.contains("Edge") || userAgent.contains("Firefox")
        );

        if (isBrowser) {
            String ip = extractRealIp(request);
            if (isTrackable(ip)) {
                clientRegistry.recordAccess(ip);
            }
        }
        chain.doFilter(request, response);
    }

    /**
     * Extracts the original client IP from proxy headers.
     * X-Forwarded-For may contain: "client, proxy1, proxy2"
     * The FIRST entry is always the original client.
     */
    private String extractRealIp(HttpServletRequest request) {
        String xff = request.getHeader("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            String first = xff.split(",")[0].trim();
            if (!first.isBlank()) return first;
        }
        String xReal = request.getHeader("X-Real-IP");
        if (xReal != null && !xReal.isBlank()) return xReal.trim();
        return request.getRemoteAddr();
    }

    /**
     * Returns true for valid IPv4 or localhost addresses from browser sessions.
     */
    private boolean isTrackable(String ip) {
        if (ip == null || ip.isBlank()) return false;
        if (ip.equals("127.0.0.1") || ip.startsWith("127.")) return true;
        if (!IPV4_PATTERN.matcher(ip).matches()) return false;
        return true;
    }


}
