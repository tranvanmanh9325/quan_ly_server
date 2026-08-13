package com.miniserver.metrics.model;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/**
 * Persisted per-sender cooldown record for Facebook Messenger Auto-Responder.
 * Survives container restarts — prevents double-reply after service redeploy.
 * senderKey = normalized sender name (lowercase trim) for case-insensitive matching.
 */
@Entity
@Table(name = "facebook_cooldown",
        indexes = @Index(name = "idx_fb_cooldown_sender", columnList = "sender_key"))
@Getter
@Setter
@NoArgsConstructor
public class FacebookCooldown {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** Normalized sender name (lowercase + trimmed). Used as lookup key. */
    @Column(name = "sender_key", nullable = false, unique = true, length = 255)
    private String senderKey;

    /** Timestamp of the last auto-reply sent to this sender. */
    @Column(name = "replied_at", nullable = false)
    private Instant repliedAt;

    public FacebookCooldown(String senderKey, Instant repliedAt) {
        this.senderKey = senderKey;
        this.repliedAt = repliedAt;
    }
}
