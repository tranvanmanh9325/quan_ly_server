package com.miniserver.metrics.model;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

/**
 * Single-row config table for Facebook Messenger Auto-Responder.
 * id is always 1 — enforced by DB CHECK constraint and seeded by migration V2.
 */
@Entity
@Table(name = "facebook_config")
@Getter
@Setter
public class FacebookConfig {

    @Id
    @Column(name = "id", nullable = false)
    private Long id = 1L;

    @Column(name = "enabled", nullable = false)
    private boolean enabled = false;

    /** Minimum unreplied incoming messages from a single user to trigger auto-reply (default: 5) */
    @Column(name = "threshold", nullable = false)
    private int threshold = 5;

    /** Minimum minutes before sending another auto-reply to the same user */
    @Column(name = "cooldown_minutes", nullable = false)
    private int cooldownMinutes = 120;

    /** Facebook Session cookies formatted as JSON string */
    @Column(name = "cookies_json", nullable = false, columnDefinition = "TEXT")
    private String cookiesJson = "";

    /** Custom template or prompt override for away message */
    @Column(name = "custom_message", nullable = false, columnDefinition = "TEXT")
    private String customMessage = "";


    @Column(name = "last_status", nullable = false, columnDefinition = "TEXT")
    private String lastStatus = "Tắt";

    @Column(name = "last_check_at")
    private LocalDateTime lastCheckAt;

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt = LocalDateTime.now();

    @PreUpdate
    public void onUpdate() {
        this.updatedAt = LocalDateTime.now();
    }
}
