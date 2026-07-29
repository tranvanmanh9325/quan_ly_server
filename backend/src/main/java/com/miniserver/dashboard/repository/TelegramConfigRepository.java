package com.miniserver.dashboard.repository;

import com.miniserver.dashboard.model.TelegramConfig;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface TelegramConfigRepository extends JpaRepository<TelegramConfig, Long> {

    /**
     * Convenience helper — always fetches the single config row (id=1).
     * Returns an empty Optional if the migration has not run yet (safe fallback).
     */
    default Optional<TelegramConfig> getConfig() {
        return findById(1L);
    }
}
