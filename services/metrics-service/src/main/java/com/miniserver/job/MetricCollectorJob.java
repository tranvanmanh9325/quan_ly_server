package com.miniserver.job;

import com.miniserver.model.ServerMetric;
import com.miniserver.repository.ServerMetricRepository;
import com.miniserver.service.SshService;
import com.miniserver.service.TelegramNotificationService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

@Component
public class MetricCollectorJob {

    private static final Logger log = LoggerFactory.getLogger(MetricCollectorJob.class);

    // Retain records for 7 days (7 * 24 * 60 = 10,080 rows max)
    private static final int RETENTION_DAYS = 7;

    private final SshService sshService;
    private final ServerMetricRepository metricRepository;
    private final TelegramNotificationService telegramService;

    public MetricCollectorJob(SshService sshService,
                              ServerMetricRepository metricRepository,
                              TelegramNotificationService telegramService) {
        this.sshService = sshService;
        this.metricRepository = metricRepository;
        this.telegramService = telegramService;
    }

    /**
     * Collect CPU, RAM, and Disk snapshot every 60 seconds and persist to PostgreSQL.
     * Uses a single SSH command batch separated by '---' markers to minimise round-trips.
     */
    @Scheduled(fixedRate = 60_000)
    public void collectMetrics() {
        try {
            // Single SSH round-trip: CPU idle%, free -m, and root disk usage%
            String cmd = "top -b -n 1 | grep 'Cpu(s)'"
                    + " && echo '---'"
                    + " && free -m"
                    + " && echo '---'"
                    + " && df / | tail -1";
            String rawData = sshService.executeCommand(cmd);

            if (rawData == null || rawData.contains("ERROR")) {
                log.warn("[MetricCollectorJob] SSH returned no data, skipping snapshot.");
                return;
            }

            String[] parts = rawData.split("---");
            if (parts.length < 3) {
                log.warn("[MetricCollectorJob] Unexpected output format, skipping snapshot.");
                return;
            }

            Double cpuPercent  = parseCpu(parts[0]);
            Double ramPercent  = parseRam(parts[1]);
            Double diskPercent = parseDisk(parts[2]);

            if (cpuPercent != null && ramPercent != null) {
                ServerMetric metric = ServerMetric.builder()
                        .timestamp(LocalDateTime.now())
                        .cpuPercent(cpuPercent)
                        .ramPercent(ramPercent)
                        .diskPercent(diskPercent)
                        .build();
                metricRepository.save(metric);
                log.debug("[MetricCollectorJob] Saved: CPU={}%, RAM={}%, Disk={}%",
                        cpuPercent, ramPercent, diskPercent);

                // Evaluate thresholds and send Telegram alert if needed
                double disk = (diskPercent != null) ? diskPercent : 0.0;
                telegramService.checkAndAlert(cpuPercent, ramPercent, disk);
            }
        } catch (Exception e) {
            log.error("[MetricCollectorJob] Error during metric collection: {}", e.getMessage());
        }
    }

    /**
     * Daily cleanup at 03:00 to enforce the 7-day retention window.
     * Uses a single bulk DELETE which is efficient for ~10k-row tables.
     * (If the table grew to millions of rows, partitioning + pg_cron would be preferred.)
     */
    @Scheduled(cron = "0 0 3 * * *")
    public void purgeOldMetrics() {
        try {
            LocalDateTime cutoff = LocalDateTime.now().minusDays(RETENTION_DAYS);
            int deleted = metricRepository.deleteOlderThan(cutoff);
            log.info("[MetricCollectorJob] Retention purge: deleted {} records older than {} days.", deleted, RETENTION_DAYS);
        } catch (Exception e) {
            log.error("[MetricCollectorJob] Error during retention purge: {}", e.getMessage());
        }
    }

    // ─── Parsers ────────────────────────────────────────────────────────────

    private Double parseCpu(String raw) {
        try {
            if (raw == null || raw.contains("ERROR")) return null;
            // Format: "%Cpu(s):  6.5 us,  7.8 sy,  0.0 ni, 85.7 id, ..."
            int idIndex = raw.indexOf(" id");
            if (idIndex != -1) {
                String sub   = raw.substring(0, idIndex).trim();
                String[] arr = sub.split(",");
                double idle  = Double.parseDouble(arr[arr.length - 1].trim());
                return Math.round((100.0 - idle) * 10.0) / 10.0;
            }
        } catch (Exception e) {
            log.error("[MetricCollectorJob] parseCpu error: {}", e.getMessage());
        }
        return null;
    }

    private Double parseRam(String raw) {
        try {
            if (raw == null || raw.contains("ERROR")) return null;
            // Format: "Mem:  total  used  free  ..."
            String[] lines = raw.strip().split("\n");
            for (String line : lines) {
                if (line.trim().startsWith("Mem:")) {
                    String[] tokens = line.trim().split("\\s+");
                    if (tokens.length >= 3) {
                        double total = Double.parseDouble(tokens[1]);
                        double used  = Double.parseDouble(tokens[2]);
                        if (total > 0) return Math.round((used / total * 100.0) * 10.0) / 10.0;
                    }
                }
            }
        } catch (Exception e) {
            log.error("[MetricCollectorJob] parseRam error: {}", e.getMessage());
        }
        return null;
    }

    private Double parseDisk(String raw) {
        try {
            if (raw == null || raw.contains("ERROR")) return null;
            // `df /` may print a 2-line output (header + data) or a single data line.
            // Always parse the last non-empty line to skip the header safely.
            String[] lines = raw.strip().split("\n");
            String dataLine = "";
            for (int i = lines.length - 1; i >= 0; i--) {
                if (!lines[i].isBlank()) { dataLine = lines[i].trim(); break; }
            }
            // df columns: Filesystem 1K-blocks Used Available Use% Mountpoint
            // Use% is at index 4 (0-based); fixed index is more robust than
            // scanning for tokens ending with '%' (could match filesystem names).
            String[] tokens = dataLine.split("\\s+");
            if (tokens.length >= 5) {
                String usePercent = tokens[4]; // e.g. "46%"
                if (usePercent.endsWith("%")) {
                    return Double.parseDouble(usePercent.replace("%", ""));
                }
            }
        } catch (Exception e) {
            log.error("[MetricCollectorJob] parseDisk error: {}", e.getMessage());
        }
        return null;
    }
}
