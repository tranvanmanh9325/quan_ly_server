package com.miniserver.dashboard.repository;

import com.miniserver.dashboard.model.ServerMetric;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

public interface ServerMetricRepository extends JpaRepository<ServerMetric, Long> {

    // Seed the real-time CPU sparkline on frontend load (last 100 records, newest first)
    List<ServerMetric> findTop100ByOrderByTimestampDesc();

    // Bounded 24h chart query: capped at 1440 rows (1 per minute × 24h).
    // The LIMIT is applied at SQL level by Spring Data, avoiding loading the full table into memory.
    List<ServerMetric> findTop1440ByTimestampAfterOrderByTimestampAsc(LocalDateTime since);

    // Data retention — hard delete records older than the given cutoff.
    // Called daily by MetricCollectorJob to keep the table bounded (~10k rows max for 7d).
    @Modifying
    @Transactional
    @Query("DELETE FROM ServerMetric m WHERE m.timestamp < :cutoff")
    int deleteOlderThan(@Param("cutoff") LocalDateTime cutoff);
}
