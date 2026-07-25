package com.miniserver.dashboard.repository;

import com.miniserver.dashboard.model.ServerMetric;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.List;
public interface ServerMetricRepository extends JpaRepository<ServerMetric, Long> {
    
    // Lấy danh sách metrics theo thời gian gần nhất (tối đa N bản ghi)
    List<ServerMetric> findTop100ByOrderByTimestampDesc();
    
    // Lấy danh sách metrics trong 24 giờ qua
    List<ServerMetric> findByTimestampAfterOrderByTimestampAsc(LocalDateTime timestamp);
}
