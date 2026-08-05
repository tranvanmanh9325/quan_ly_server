package com.miniserver.metrics.service;

import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * Centralizes RestClient creation with explicit timeouts.
 *
 * Without timeouts, RestClient.create() blocks indefinitely — a potential thread starvation
 * risk in scheduled tasks (e.g., Telegram polling) if the remote API hangs.
 */
public final class RestClientFactory {

    private RestClientFactory() {
        // Utility class — no instantiation
    }

    /**
     * @param connectTimeoutMs TCP connection establishment timeout
     * @param readTimeoutMs    Socket read timeout (must be > expected API response time)
     */
    public static RestClient create(int connectTimeoutMs, int readTimeoutMs) {
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeoutMs);
        factory.setReadTimeout(readTimeoutMs);
        return RestClient.builder().requestFactory(factory).build();
    }
}
