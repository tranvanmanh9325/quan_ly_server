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
 * Stores structured data per sender:
 *   - incomingMessages: The actual messages sent by the contact (separated from bot replies)
 *   - lastReplySent: The text of the away message / direct reply sent by the bot (if any)
 *   - threadHref: Direct URL to the conversation
 *   - wasAutoReplied: Whether an automated away response was dispatched
 */
@Component
public class FacebookMessageCache {

    private static final int HISTORY_LIMIT = 50;

    private static final DateTimeFormatter VN_FMT =
            DateTimeFormatter.ofPattern("HH:mm dd/MM/yyyy");

    private final CopyOnWriteArrayList<Entry> entries = new CopyOnWriteArrayList<>();

    private volatile LocalDateTime lastScanAt;

    // ── Public write API ──────────────────────────────────────────────────────

    /**
     * Records full message details with structured incoming messages list.
     */
    public void addOrUpdate(String senderName, List<String> incomingMessages,
                            String lastReplySent, String threadHref, boolean wasAutoReplied) {
        if (senderName == null || senderName.isBlank()) return;

        String cleanSender = senderName.trim();
        List<String> cleanIncoming = new ArrayList<>();
        if (incomingMessages != null) {
            for (String msg : incomingMessages) {
                if (msg != null && !msg.isBlank()) {
                    cleanIncoming.add(msg.trim());
                }
            }
        }

        // If updating an existing entry and new incoming is empty, preserve previous incoming
        Entry existing = findEntry(cleanSender);
        if (cleanIncoming.isEmpty() && existing != null && !existing.incomingMessages().isEmpty()) {
            cleanIncoming.addAll(existing.incomingMessages());
        }

        String replyToStore = (lastReplySent != null && !lastReplySent.isBlank())
                ? lastReplySent.trim()
                : (existing != null ? existing.lastReplySent() : "");

        String hrefToStore = (threadHref != null && !threadHref.isBlank())
                ? threadHref.trim()
                : (existing != null ? existing.threadHref() : "");

        boolean autoRepliedToStore = wasAutoReplied || (existing != null && existing.wasAutoReplied());

        entries.removeIf(e -> e.senderName().equalsIgnoreCase(cleanSender));

        Entry entry = new Entry(
                cleanSender,
                Collections.unmodifiableList(cleanIncoming),
                replyToStore,
                hrefToStore,
                LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh")),
                autoRepliedToStore
        );
        entries.add(0, entry);

        while (entries.size() > HISTORY_LIMIT) {
            entries.remove(entries.size() - 1);
        }
    }

    /**
     * Backward-compatible overload for single preview string.
     */
    public void addOrUpdate(String senderName, String preview, String threadHref, boolean wasAutoReplied) {
        if (senderName == null || senderName.isBlank()) return;
        List<String> incoming = new ArrayList<>();
        if (preview != null && !preview.isBlank() && !preview.startsWith("[Auto-reply")) {
            incoming.add(preview.trim());
        }
        String reply = (preview != null && preview.startsWith("[Auto-reply")) ? preview : "";
        addOrUpdate(senderName, incoming, reply, threadHref, wasAutoReplied);
    }

    /**
     * Records a direct reply sent manually or by AI agent.
     */
    public void recordDirectReply(String senderName, String replyMessage) {
        if (senderName == null || senderName.isBlank()) return;
        Entry existing = findEntry(senderName);
        if (existing != null) {
            addOrUpdate(existing.senderName(), existing.incomingMessages(), replyMessage, existing.threadHref(), true);
        }
    }

    public void markScanCompleted() {
        this.lastScanAt = LocalDateTime.now(java.time.ZoneId.of("Asia/Ho_Chi_Minh"));
    }

    // ── Public read API ───────────────────────────────────────────────────────

    public List<Entry> getAll() {
        return Collections.unmodifiableList(new ArrayList<>(entries));
    }

    public LocalDateTime getLastScanAt() {
        return lastScanAt;
    }

    public Entry findEntry(String senderName) {
        if (senderName == null || senderName.isBlank()) return null;
        String query = senderName.trim().toLowerCase();
        return entries.stream()
                .filter(e -> e.senderName().toLowerCase().contains(query)
                          || query.contains(e.senderName().toLowerCase()))
                .findFirst()
                .orElse(null);
    }

    public String findThreadHref(String senderName) {
        Entry e = findEntry(senderName);
        return e != null ? e.threadHref() : null;
    }

    /**
     * Formats the entire cache as a structured, unambiguous summary for the AI agent.
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
        sb.append("Danh sách tin nhắn Facebook được ghi nhận (").append(entries.size()).append(" người):\n\n");

        int idx = 1;
        for (Entry e : entries) {
            sb.append(idx++).append(". 👤 Người gửi: ").append(e.senderName()).append("\n");

            List<String> msgs = e.incomingMessages();
            if (!msgs.isEmpty()) {
                sb.append("   📩 Nội dung tin nhắn người gửi đã nhắn:\n");
                for (String m : msgs) {
                    sb.append("      • \"").append(m).append("\"\n");
                }
            } else {
                sb.append("   📩 Nội dung tin nhắn người gửi đã nhắn: (Không có tin nhắn mới)\n");
            }

            if (e.lastReplySent() != null && !e.lastReplySent().isBlank()) {
                sb.append("   🤖 Trợ lý AI đã trả lời: \"").append(e.lastReplySent()).append("\"\n");
            }

            if (e.wasAutoReplied()) {
                sb.append("   ✅ Trạng thái: Đã gửi phản hồi tự động.\n");
            } else {
                sb.append("   ⏳ Trạng thái: Chưa trả lời.\n");
            }

            sb.append("   🕐 Ghi nhận lúc: ").append(e.detectedAt().format(VN_FMT)).append("\n");
            sb.append("   🔗 Thread URL: ").append(e.threadHref()).append("\n\n");
        }
        return sb.toString().trim();
    }

    // ── Entry record ──────────────────────────────────────────────────────────

    public record Entry(
            String senderName,
            List<String> incomingMessages,
            String lastReplySent,
            String threadHref,
            LocalDateTime detectedAt,
            boolean wasAutoReplied
    ) {}
}

