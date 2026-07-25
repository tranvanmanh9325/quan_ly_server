package com.miniserver.dashboard.job;

import com.miniserver.dashboard.model.ServerMetric;
import com.miniserver.dashboard.repository.ServerMetricRepository;
import com.miniserver.dashboard.service.SshService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

@Component
public class MetricCollectorJob {

    private static final Logger log = LoggerFactory.getLogger(MetricCollectorJob.class);

    private final SshService sshService;
    private final ServerMetricRepository metricRepository;

    public MetricCollectorJob(SshService sshService, ServerMetricRepository metricRepository) {
        this.sshService = sshService;
        this.metricRepository = metricRepository;
    }

    // Chạy ngầm mỗi 1 phút (60000ms)
    @Scheduled(fixedRate = 60000)
    public void collectMetrics() {
        try {
            log.info("Bắt đầu thu thập dữ liệu lịch sử...");
            
            // Gộp lệnh lấy CPU và RAM vào 1 session SSH duy nhất để giảm tải kết nối
            String combinedCmd = "top -b -n 1 | grep 'Cpu(s)' && echo '---' && free -m";
            String rawData = sshService.executeCommand(combinedCmd);

            if (rawData != null && !rawData.contains("ERROR")) {
                String[] parts = rawData.split("---");
                if (parts.length == 2) {
                    Double cpuPercent = parseCpu(parts[0]);
                    Double ramPercent = parseRam(parts[1]);

                    // Lưu vào DB
                    if (cpuPercent != null && ramPercent != null) {
                        ServerMetric metric = new ServerMetric(LocalDateTime.now(), cpuPercent, ramPercent);
                        metricRepository.save(metric);
                        log.info("Đã lưu lịch sử: CPU {}%, RAM {}%", cpuPercent, ramPercent);
                    }
                }
            }
        } catch (Exception e) {
            log.error("Lỗi khi thu thập dữ liệu lịch sử: {}", e.getMessage());
        }
    }

    private Double parseCpu(String raw) {
        try {
            if (raw == null || raw.contains("ERROR")) return null;
            // Dạng: "%Cpu(s):  6.5 us,  7.8 sy,  0.0 ni, 85.7 id, ..."
            int idIndex = raw.indexOf(" id");
            if (idIndex != -1) {
                String sub = raw.substring(0, idIndex).trim();
                String[] parts = sub.split(",");
                String idStr = parts[parts.length - 1].trim(); // "85.7"
                double idVal = Double.parseDouble(idStr);
                return Math.round((100.0 - idVal) * 10.0) / 10.0;
            }
        } catch (Exception e) {
            log.error("Lỗi parse CPU: {}", e.getMessage());
        }
        return null;
    }

    private Double parseRam(String raw) {
        try {
            if (raw == null || raw.contains("ERROR")) return null;
            String[] lines = raw.split("\n");
            if (lines.length > 1) {
                String memLine = lines[1];
                String[] tokens = memLine.trim().split("\\s+");
                if (tokens.length >= 3) {
                    double total = Double.parseDouble(tokens[1]);
                    double used = Double.parseDouble(tokens[2]);
                    if (total > 0) {
                        return Math.round((used / total * 100.0) * 10.0) / 10.0;
                    }
                }
            }
        } catch (Exception e) {
            log.error("Lỗi parse RAM: {}", e.getMessage());
        }
        return null;
    }
}
