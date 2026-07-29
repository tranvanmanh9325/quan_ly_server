package com.miniserver.dashboard.model;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

/**
 * Single-row config table for Telegram Bot integration.
 * id is always 1 — enforced by DB CHECK constraint and seeded by migration V3.
 * Use TelegramConfigRepository.getConfig() to retrieve; never create new instances directly.
 */
@Entity
@Table(name = "telegram_config")
@Getter
@Setter
public class TelegramConfig {

    @Id
    @Column(name = "id", nullable = false)
    private Long id = 1L;

    @Column(name = "bot_token", nullable = false)
    private String botToken = "";

    @Column(name = "chat_id", nullable = false)
    private String chatId = "";

    @Column(name = "enabled", nullable = false)
    private boolean enabled = false;

    /** Alert threshold: send notification when CPU% exceeds this value */
    @Column(name = "cpu_threshold", nullable = false)
    private int cpuThreshold = 80;

    /** Alert threshold: send notification when RAM% exceeds this value */
    @Column(name = "ram_threshold", nullable = false)
    private int ramThreshold = 85;

    /** Alert threshold: send notification when any disk partition% exceeds this value */
    @Column(name = "disk_threshold", nullable = false)
    private int diskThreshold = 90;

    /** Minimum minutes between two consecutive alerts of the same type to avoid spam */
    @Column(name = "cooldown_minutes", nullable = false)
    private int cooldownMinutes = 15;

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt = LocalDateTime.now();

    @PreUpdate
    public void onUpdate() {
        this.updatedAt = LocalDateTime.now();
    }
}
