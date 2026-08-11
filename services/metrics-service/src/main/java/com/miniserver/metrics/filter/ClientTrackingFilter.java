package com.miniserver.metrics.filter;

import com.miniserver.metrics.service.ActiveClientRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
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

    @Autowired
    private ActiveClientRegistry clientRegistry;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain)
            throws ServletException, IOException {
        String ip = extractRealIp(request);
        if (isTrackable(ip)) {
            clientRegistry.recordAccess(ip);
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
     * Returns true for IPs we want to show on the map:
     * - Must be a valid IPv4 address
     * - Not loopback (127.x.x.x)
     * - Not Docker bridge range (172.16.0.0/12 = 172.16–172.31)
     * LAN ranges (10.x, 192.168.x) are allowed — shown at server coordinates.
     */
    private boolean isTrackable(String ip) {
        if (ip == null || ip.isBlank()) return false;
        if (!IPV4_PATTERN.matcher(ip).matches()) return false;
        if (ip.startsWith("127.")) return false;
        if (ip.startsWith("172.")) {
            try {
                int second = Integer.parseInt(ip.split("\\.")[1]);
                if (second >= 16 && second <= 31) return false;
            } catch (NumberFormatException ignored) { return false; }
        }
        return true;
    }
}
