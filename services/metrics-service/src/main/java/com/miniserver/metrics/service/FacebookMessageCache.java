package com.miniserver.metrics.service;

import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Thread-safe in-memory cache of recent Facebook Messenger activity.
 *
 * Updated by {@link FacebookMessengerService} after each scan cycle.
 * Read by {@link AiChatService} via the {@code facebook_get_messages} tool so the AI
 * can answer natural-language questions like "Ai đã nhắn cho tôi lúc vắng mặt?".
 *
 * Uses CopyOnWriteArrayList to allow lock-free concurrent reads while scan writes happen.
 * Maximum capacity is capped at HISTORY_LIMIT entries to prevent unbounded growth.
 */
@Component
public class FacebookMessageCache {

    /** Maximum number of message entries to keep in memory. */
    private static final int HISTORY_LIMIT = 50;

    private static final DateTimeFormatter VN_FMT =
            DateTimeFormatter.ofPattern("HH:mm dd/MM/yyyy");

    private final CopyOnWriteArrayList<Entry> entries = new CopyOnWriteArrayList<>();

    /** Timestamp of the last successful scan cycle. */
    private volatile LocalDateTime lastScanAt;

    // ── Public write API (called by FacebookMessengerService) ─────────────────

    /**
     * Records a message detected during a scan cycle.
     *
     * @param senderName     display name of the sender
     * @param preview        first 100 chars of message preview from the sidebar
     * @param threadHref     full URL of the Messenger thread (used for navigation on reply)
     * @param wasAutoReplied whether an auto-reply was already sent in this scan cycle
     */
    public void addOrUpdate(String senderName, String preview, String threadHref, boolean wasAutoReplied) {
        if (senderName == null || senderName.isBlank()) return;

        // Replace existing entry for the same sender (avoid duplicates across scan cycles)
        entries.removeIf(e -> e.senderName().equalsIgnoreCase(senderName));

        Entry entry = new Entry(
                senderName.trim(),
                preview != null ? preview.trim() : "",
                threadHref != null ? threadHref.trim() : "",
                LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")),
                wasAutoReplied
        );
        entries.add(0, entry); // newest first

        // Cap at HISTORY_LIMIT
        while (entries.size() > HISTORY_LIMIT) {
            entries.remove(entries.size() - 1);
        }
    }

    /** Updates the last-scan timestamp. Called at the end of each successful scan. */
    public void markScanCompleted() {
        this.lastScanAt = LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh"));
    }

    // ── Public read API (called by AiChatService) ─────────────────────────────

    /** Returns an immutable snapshot of all cached entries, newest first. */
    public List<Entry> getAll() {
        return Collections.unmodifiableList(new ArrayList<>(entries));
    }

    /** Returns the last scan time, or null if no scan has completed yet. */
    public LocalDateTime getLastScanAt() {
        return lastScanAt;
    }

    /**
     * Formats the entire cache as a human-readable Vietnamese string
     * suitable for returning to the AI as tool output.
     */
    public String toAiSummary() {
        if (entries.isEmpty()) {
            String scanInfo = lastScanAt != null
                    ? " Lần quét gần nhất: " + lastScanAt.format(VN_FMT) + "."
                    : " Chưa có lần quét nào hoàn thành.";
            return "Không có tin nhắn Facebook nào được ghi nhận kể từ lần quét gần nhất." + scanInfo;
        }

        StringBuilder sb = new StringBuilder();
        if (lastScanAt != null) {
            sb.append("Lần quét Facebook gần nhất: ").append(lastScanAt.format(VN_FMT)).append("\n");
        }
        sb.append("Danh sách tin nhắn phát hiện được (").append(entries.size()).append(" người):\n\n");

        int idx = 1;
        for (Entry e : entries) {
            sb.append(idx++).append(". 👤 ").append(e.senderName()).append("\n");
            String preview = e.preview();
            if (!preview.isBlank()) {
                sb.append("   💬 Preview: \"").append(preview, 0, Math.min(preview.length(), 80)).append("\"\n");
            }
            sb.append("   🕐 Phát hiện lúc: ").append(e.detectedAt().format(VN_FMT)).append("\n");
            sb.append("   🔗 Thread: ").append(e.threadHref()).append("\n");
            if (e.wasAutoReplied()) {
                sb.append("   ✅ Đã tự động trả lời vắng mặt.\n");
            } else {
                sb.append("   ⏳ Chưa trả lời.\n");
            }
            sb.append("\n");
        }
        return sb.toString().trim();
    }

    /**
     * Finds the thread href for a given sender name using fuzzy matching.
     * Returns null if not found.
     */
    public String findThreadHref(String senderName) {
        if (senderName == null || senderName.isBlank()) return null;
        String query = senderName.trim().toLowerCase();

        return entries.stream()
                .filter(e -> e.senderName().toLowerCase().contains(query)
                          || query.contains(e.senderName().toLowerCase()))
                .map(Entry::threadHref)
                .filter(h -> h != null && !h.isBlank())
                .findFirst()
                .orElse(null);
    }

    // ── Entry record ──────────────────────────────────────────────────────────

    public record Entry(
            String senderName,
            String preview,
            String threadHref,
            LocalDateTime detectedAt,
            boolean wasAutoReplied
    ) {}
}
