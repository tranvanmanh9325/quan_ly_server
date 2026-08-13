package com.miniserver.metrics.repository;

import com.miniserver.metrics.model.FacebookCooldown;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Optional;

public interface FacebookCooldownRepository extends JpaRepository<FacebookCooldown, Long> {

    Optional<FacebookCooldown> findBySenderKey(String senderKey);

    /** Upsert via PostgreSQL ON CONFLICT: insert if new, update repliedAt if exists. */
    @Modifying
    @Transactional
    @Query(value = "INSERT INTO facebook_cooldown (sender_key, replied_at) VALUES (:senderKey, :repliedAt) ON CONFLICT (sender_key) DO UPDATE SET replied_at = :repliedAt",
           nativeQuery = true)
    void upsert(@Param("senderKey") String senderKey, @Param("repliedAt") Instant repliedAt);

    /** Delete stale rows older than :before to keep the table lean. */
    @Modifying
    @Transactional
    @Query("DELETE FROM FacebookCooldown c WHERE c.repliedAt < :before")
    void deleteExpiredBefore(@Param("before") Instant before);
}
