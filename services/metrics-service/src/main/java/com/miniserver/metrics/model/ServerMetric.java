package com.miniserver.metrics.model;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Entity
@Table(name = "server_metrics")
public class ServerMetric {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private LocalDateTime timestamp;

    @Column(name = "cpu_percent")
    private Double cpuPercent;

    @Column(name = "ram_percent")
    private Double ramPercent;

    @Column(name = "disk_percent")
    private Double diskPercent;
}
