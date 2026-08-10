package com.miniserver.metrics.repository;

import com.miniserver.metrics.model.FacebookConfig;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface FacebookConfigRepository extends JpaRepository<FacebookConfig, Long> {

    /**
     * Convenience helper — always fetches the single config row (id=1).
     * Returns an empty Optional if migration has not run yet.
     */
    default Optional<FacebookConfig> getConfig() {
        return findById(1L);
    }
}
