package com.miniserver.metrics.job;

import com.miniserver.metrics.model.ServerMetric;
import com.miniserver.metrics.repository.ServerMetricRepository;
import com.miniserver.metrics.service.SshService;
import com.miniserver.metrics.service.TelegramNotificationService;
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
     * Collect CPU, RAM, and Disk snapshot every 60 seconds (with 2s initial delay on startup)
     * and persist directly to PostgreSQL.
     *
     * CPU is measured by reading /proc/stat twice with a 300ms gap in-memory:
     * - Pure in-memory pipe (zero temporary files written to disk)
     * - Zero process spawn overhead for AWK
     * - Direct delta calculation: cpu_used% = (1 - idle_delta / total_delta) * 100
     */
    @Scheduled(fixedRate = 60_000, initialDelay = 2_000)
    public void collectMetrics() {
        try {
            String cmd = "(cat /proc/stat; sleep 0.3; cat /proc/stat) | awk '/^cpu / { if (!seen) { for(i=2;i<=NF;i++) a[i]=$i; seen=1 } else { t=0; id=0; for(i=2;i<=NF;i++){ d=$i-a[i]; t+=d; if(i==5) id=d }; if (t>0) printf \"%.1f\\n\", (1-id/t)*100; exit } }'"
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
                log.warn("[MetricCollectorJob] Unexpected output format, skipping snapshot: {}", rawData);
                return;
            }

            Double cpuPercent  = parseCpuDirect(parts[0]);
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
                log.info("[MetricCollectorJob] Snapshot saved successfully: CPU={}%, RAM={}%, Disk={}%",
                        cpuPercent, ramPercent, diskPercent);

                // Evaluate thresholds and send Telegram alert if needed
                double disk = (diskPercent != null) ? diskPercent : 0.0;
                telegramService.checkAndAlert(cpuPercent, ramPercent, disk);
            } else {
                log.warn("[MetricCollectorJob] Failed to parse metrics (cpu={}, ram={}) from rawData:\n{}",
                        cpuPercent, ramPercent, rawData);
            }
        } catch (Exception e) {
            log.error("[MetricCollectorJob] Error during metric collection: {}", e.getMessage(), e);
        }
    }

    /**
     * Daily cleanup at 03:00 to enforce the 7-day retention window.
     * Uses a single bulk DELETE which is efficient for ~10k-row tables.
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

    /**
     * Parses CPU usage from a plain float string produced by the /proc/stat awk delta method.
     * Input example: "12.3" or " 12.3\n"
     * Falls back to legacy 'top' format parsing if delta method fails.
     */
    private Double parseCpuDirect(String raw) {
        try {
            if (raw == null || raw.contains("ERROR")) return null;
            String trimmed = raw.trim();
            // Try direct float first (new /proc/stat delta format)
            if (trimmed.matches("^[0-9]+(\\.[0-9]+)?$")) {
                double value = Double.parseDouble(trimmed);
                return Math.round(value * 10.0) / 10.0;
            }
            // Fallback: legacy top format "%Cpu(s):  6.5 us,  7.8 sy,  0.0 ni, 85.7 id, ..."
            return parseCpuLegacy(trimmed);
        } catch (Exception e) {
            log.error("[MetricCollectorJob] parseCpuDirect error: {}", e.getMessage());
        }
        return null;
    }

    /** Legacy top-output parser kept as fallback. */
    private Double parseCpuLegacy(String raw) {
        try {
            int idIndex = raw.indexOf(" id");
            if (idIndex != -1) {
                String sub   = raw.substring(0, idIndex).trim();
                String[] arr = sub.split(",");
                double idle  = Double.parseDouble(arr[arr.length - 1].trim());
                return Math.round((100.0 - idle) * 10.0) / 10.0;
            }
        } catch (Exception ignored) {}
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
            String[] lines = raw.strip().split("\n");
            String dataLine = "";
            for (int i = lines.length - 1; i >= 0; i--) {
                if (!lines[i].isBlank()) { dataLine = lines[i].trim(); break; }
            }
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
