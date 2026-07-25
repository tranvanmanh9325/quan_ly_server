package com.miniserver.dashboard.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

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

    public ServerMetric() {
    }

    public ServerMetric(LocalDateTime timestamp, Double cpuPercent, Double ramPercent) {
        this.timestamp = timestamp;
        this.cpuPercent = cpuPercent;
        this.ramPercent = ramPercent;
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public LocalDateTime getTimestamp() {
        return timestamp;
    }

    public void setTimestamp(LocalDateTime timestamp) {
        this.timestamp = timestamp;
    }

    public Double getCpuPercent() {
        return cpuPercent;
    }

    public void setCpuPercent(Double cpuPercent) {
        this.cpuPercent = cpuPercent;
    }

    public Double getRamPercent() {
        return ramPercent;
    }

    public void setRamPercent(Double ramPercent) {
        this.ramPercent = ramPercent;
    }
}
