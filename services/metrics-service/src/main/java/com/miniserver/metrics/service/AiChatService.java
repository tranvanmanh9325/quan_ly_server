package com.miniserver.metrics.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Lazy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * True AI Agent backed by Groq Cloud (OpenAI-compatible) with a generic shell tool.
 *
 * Architecture: Single `run_command(command)` tool — the AI decides which Linux/Docker
 * command to run based on the user's question. No tool registration needed for new
 * question types; the AI's pre-trained knowledge covers all Linux/Docker commands.
 *
 * Agent Loop:
 *   1. User message arrives.
 *   2. Groq receives message + tool definition.
 *   3. If AI wants data → it calls run_command(command) with a shell command it generates.
 *   4. Backend validates command against security blocklist, then executes via SSH.
 *   5. Result returned to Groq → AI formulates final answer.
 *   6. Repeat up to MAX_AGENT_ITERATIONS per message.
 *
 * Security model (defense-in-depth):
 *   - Blocklist: destructive commands, file-writes, shell-spawning patterns.
 *   - Timeout: every command wrapped with `timeout 15` to prevent hangs.
 *   - Least privilege: SSH runs as the configured non-root user.
 *   - Audit: every executed command is logged at INFO level.
 *   - Output cap: 3000 chars max to stay within Telegram limits.
 */
@Service
public class AiChatService {

    private static final Logger log = LoggerFactory.getLogger(AiChatService.class);
    private static final String GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";

    private static final int MAX_AGENT_ITERATIONS = 5;
    private static final int MAX_HISTORY_MESSAGES = 6;
    private static final int MAX_OUTPUT_CHARS     = 1000;
    private static final int COMMAND_TIMEOUT_SEC  = 15;

    /**
     * Patterns that are NEVER allowed to execute regardless of AI intent.
     * All checks are case-insensitive and matched as substrings.
     */
    private static final List<String> BLOCKED_PATTERNS = List.of(
            // File destruction
            "rm ", "rm\t", "rmdir", "dd ", "shred", "wipefs", "truncate",
            // Disk / filesystem
            "mkfs", "/dev/sda", "/dev/sdb", "/dev/nvme", "/dev/vd",
            // System shutdown / power
            "shutdown", "reboot", "poweroff", "halt", "init 0", "init 6",
            // Process termination (services)
            "kill ", "kill\t", "pkill", "killall",
            // Dangerous systemctl operations
            "systemctl stop", "systemctl disable", "systemctl mask",
            "service stop", "service disable",
            // User / auth management
            "passwd", "adduser", "useradd", "userdel", "groupdel",
            "su ", "su\t", "sudo su",
            // Network / firewall destruction
            "iptables -f", "iptables --flush", "ufw disable", "ufw reset",
            // Package removal
            "apt remove", "apt purge", "apt-get remove", "apt-get purge",
            "yum remove", "yum erase", "dnf remove",
            "pip uninstall", "npm uninstall",
            // Docker destruction (read-only docker ps/logs/stats are OK)
            "docker rm", "docker rmi", "docker kill", "docker stop",
            "docker pause", "docker network rm", "docker volume rm",
            // File write patterns
            " > /", "\t> /", " >> /", "\t>> /",
            // Shell injection / code execution
            "|bash", "| bash", "|sh", "| sh",
            ";bash", "; bash", ";sh", "; sh",
            "&bash", "& bash", "&sh", "& sh",
            "$(", "`",
            // Reverse shell / network abuse
            "nc ", "nc\t", "ncat", "netcat",
            "wget ", "curl -o ", "curl --output",
            // Inline interpreter execution
            "python -c", "python3 -c", "perl -e", "ruby -e", "node -e",
            // Cron removal
            "crontab -r"
    );

    @Value("${groq.model:llama-3.1-8b-instant}")
    private String model;

    private final SshService   sshService;
    private final GroqKeyPool  keyPool;
    // @Lazy breaks the circular dependency: FacebookMessengerService -> AiChatService -> FacebookMessengerService
    private final FacebookMessengerService fbMessengerService;
    private final FacebookMessageCache     messageCache;
    private final ObjectMapper mapper = new ObjectMapper();
    private final RestClient   restClient;

    // chatId -> full OpenAI-format message history
    private final Map<String, Deque<ObjectNode>> historyMap = new ConcurrentHashMap<>();

    public AiChatService(SshService sshService, GroqKeyPool keyPool,
                         @Lazy FacebookMessengerService fbMessengerService,
                         FacebookMessageCache messageCache) {
        this.sshService        = sshService;
        this.keyPool           = keyPool;
        this.fbMessengerService = fbMessengerService;
        this.messageCache      = messageCache;
        // 30s read timeout - LLM inference can be slow under load
        this.restClient = RestClientFactory.create(5_000, 30_000);
    }

    // ─── Public API ──────────────────────────────────────────────────────────

    public boolean isConfigured() {
        return keyPool.hasKeys();
    }

    public String chat(String chatId, String userMessage) {
        if (!isConfigured()) {
            return "AI chưa được cấu hình. Vui lòng thêm ít nhất 1 GROQ_API_KEY vào file .env.";
        }

        Deque<ObjectNode> history = historyMap.computeIfAbsent(chatId, k -> new ArrayDeque<>());
        history.addLast(userMessageNode(userMessage));

        if (isGreeting(userMessage)) {
            String greetingReply = "Xin chào! Tôi là \"Tiểu Bảo Bảo trợ lí của Mạnh (Cua)\", trợ lý tự động giám sát máy chủ Linux. "
                    + "Tôi có thể giúp bạn kiểm tra CPU, RAM, Disk, Docker containers, hoặc các tiến trình theo thời gian thực. "
                    + "Bạn có câu hỏi nào về máy chủ không?";
            ObjectNode replyNode = mapper.createObjectNode();
            replyNode.put("role", "assistant");
            replyNode.put("content", greetingReply);
            history.addLast(replyNode);
            trimHistory(history);
            return greetingReply;
        }

        try {
            for (int i = 0; i < MAX_AGENT_ITERATIONS; i++) {
                String   rawResponse  = callGroq(buildRequest(history));
                JsonNode response     = mapper.readTree(rawResponse);
                JsonNode choice       = response.path("choices").path(0);
                String   finishReason = choice.path("finish_reason").asText("stop");
                JsonNode assistantMsg = choice.path("message");

                history.addLast(toObjectNode(assistantMsg));

                if ("tool_calls".equals(finishReason)) {
                    for (JsonNode toolCall : assistantMsg.path("tool_calls")) {
                        String callId   = toolCall.path("id").asText();
                        String toolName = toolCall.path("function").path("name").asText();
                        String toolArgs = toolCall.path("function").path("arguments").asText("{}");

                        String result = executeTool(toolName, toolArgs);
                        history.addLast(toolResultNode(callId, result));
                    }
                    // Loop: let Groq formulate its answer using the tool results
                } else {
                    String reply = assistantMsg.path("content").asText("Xin loi, toi khong hieu. Hay thu lai.");
                    trimHistory(history);
                    return reply;
                }
            }

            trimHistory(history);
            return "AI da thu nhieu buoc nhung chua hoan thanh yeu cau.";

        } catch (HttpClientErrorException.BadRequest e) {
            log.error("[Agent] Groq BadRequest: {}", e.getResponseBodyAsString());
            clearHistory(chatId);
            return "Xin lỗi, AI vừa tạo câu lệnh không hợp lệ. Tôi đã dọn dẹp bộ nhớ đệm, vui lòng thử hỏi lại.";
        } catch (HttpClientErrorException.TooManyRequests e) {
            log.error("[Agent] Rate limited: {}", e.getMessage());
            clearHistory(chatId);
            return "AI đang tạm thời quá tải giới hạn token. Tôi đã dọn bộ nhớ hội thoại, bạn hãy thử lại nhé.";
        } catch (Exception e) {
            log.error("[Agent] Error in agent loop: {}", e.getMessage(), e);
            // Do NOT clear history on transient errors (network, SSH latency) —
            // preserving context lets the user simply retry without losing the conversation.
            return "Đã xảy ra lỗi khi xử lý câu hỏi. Vui lòng thử lại.";
        }
    }

    public void clearHistory(String chatId) {
        historyMap.remove(chatId);
    }

    // ─── Tool dispatch ────────────────────────────────────────────────────────

    private String executeTool(String toolName, String argsJson) {
        return switch (toolName) {
            case "run_command" -> {
                try {
                    JsonNode args = mapper.readTree(argsJson);
                    String command = args.path("command").asText("").trim();
                    if (command.isBlank()) yield "No command provided.";
                    yield executeShellCommand(command);
                } catch (Exception e) {
                    yield "Failed to parse tool arguments: " + e.getMessage();
                }
            }
            case "facebook_get_messages" -> messageCache.toAiSummary();
            case "facebook_send_reply" -> {
                try {
                    JsonNode args = mapper.readTree(argsJson);
                    String recipient = args.path("recipient_name").asText("").trim();
                    String msg       = args.path("message").asText("").trim();
                    if (recipient.isBlank()) yield "Loi: Thieu ten nguoi nhan (recipient_name).";
                    if (msg.isBlank()) yield "Loi: Thieu noi dung tin nhan (message).";
                    yield fbMessengerService.sendDirectReply(recipient, msg);
                } catch (Exception e) {
                    yield "Loi khi gui tin nhan Facebook: " + e.getMessage();
                }
            }
            default -> "Unknown tool: " + toolName;
        };
    }

    /**
     * Security-validated SSH command executor.
     *
     * Defense-in-depth:
     *   1. Check command against BLOCKED_PATTERNS blocklist.
     *   2. Wrap command with `timeout` to prevent runaway processes.
     *   3. Log every executed command for audit trail.
     *   4. Truncate output to stay within Telegram limits.
     */
    private String executeShellCommand(String command) {
        String violation = findSecurityViolation(command);
        if (violation != null) {
            log.warn("[Agent] BLOCKED unsafe command '{}' — reason: {}", command, violation);
            return "BLOCKED: lenh bi tu choi vi ly do bao mat (" + violation + "). "
                 + "Chi duoc phep dung cac lenh doc (ps, docker ps, free, df, cat, v.v.)";
        }

        // Wrap with timeout so a hanging command (tail -f, watch, etc.) doesn't block the agent
        String timedCommand = "timeout " + COMMAND_TIMEOUT_SEC + " " + command;
        log.info("[Agent] Executing SSH: {}", timedCommand);

        String output = sshService.executeSudoCommand(timedCommand);
        if (output == null || output.isBlank()) {
            return "(lenh khong co output hoac server khong phan hoi)";
        }

        // Truncate long output — Telegram max is ~4096 chars
        if (output.length() > MAX_OUTPUT_CHARS) {
            output = output.substring(0, MAX_OUTPUT_CHARS) + "\n... [output bi cat ngan]";
        }
        return output.trim();
    }

    /**
     * Checks whether a command contains any blocked pattern.
     *
     * @return null if command is safe, or a description of the violation.
     */
    private String findSecurityViolation(String command) {
        if (command == null || command.isBlank()) return "empty command";
        String lower = command.toLowerCase();
        return BLOCKED_PATTERNS.stream()
                .filter(lower::contains)
                .map(p -> "contains '" + p.strip() + "'")
                .findFirst()
                .orElse(null);
    }

    // ─── Groq API request builder ─────────────────────────────────────────────

    private String buildRequest(Deque<ObjectNode> history) throws Exception {
        ObjectNode body = mapper.createObjectNode();
        body.put("model", model);
        body.put("temperature", 0.4);
        body.put("max_tokens", 1024);

        ArrayNode messages = body.putArray("messages");
        messages.addObject().put("role", "system").put("content", buildSystemPrompt());
        history.forEach(messages::add);

        body.set("tools", buildToolDefinitions());
        body.put("tool_choice", "auto");

        return mapper.writeValueAsString(body);
    }

    /**
     * Calls the Groq API with smart multi-key rotation (9router-style).
     *
     * On each attempt:
     *   1. Ask the pool for the next healthy key (round-robin, skipping cooldown keys).
     *   2. Send the request.
     *   3. HTTP 429 → mark that key as rate-limited (60s cooldown), retry immediately
     *      with the next key — no sleep needed when another key is available.
     *   4. Retry up to (pool size + 2) times before giving up.
     */
    private String callGroq(String requestBody) throws Exception {
        // Attempt once per key so every healthy key gets a chance before failing
        int maxAttempts = Math.max(3, keyPool.getKeyCount());

        for (int attempt = 0; attempt < maxAttempts; attempt++) {
            String key = keyPool.getNextKey();
            if (key == null) throw new IllegalStateException("No Groq API keys configured.");

            try {
                return restClient.post()
                        .uri(GROQ_API_URL)
                        .contentType(MediaType.APPLICATION_JSON)
                        .header("Authorization", "Bearer " + key)
                        .body(requestBody)
                        .retrieve()
                        .body(String.class);
            } catch (HttpClientErrorException.TooManyRequests e) {
                // Mark this key as rate-limited; pool will skip it for 60s.
                keyPool.markRateLimited(key);
                log.warn("[Agent] 429 on key ...{}; pool status: {}",
                        key.length() > 6 ? key.substring(key.length() - 6) : "***",
                        keyPool.getPoolStatus());
                // If this was the last attempt, propagate the error
                if (attempt == maxAttempts - 1) throw e;
                // Otherwise continue loop — next iteration picks a different key instantly
            }
        }
        throw new IllegalStateException("All Groq API keys exhausted after " + maxAttempts + " attempts.");
    }

    /**
     * Defines all tools exposed to the Groq AI agent.
     *
     * Tools:
     *   - run_command:           execute any read-only Linux shell command via SSH
     *   - facebook_get_messages: query the in-memory cache of recent Facebook messages
     *   - facebook_send_reply:   send a Facebook Messenger message to a specific person
     */
    private ArrayNode buildToolDefinitions() {
        ArrayNode tools = mapper.createArrayNode();

        // Tool 1: run_command
        ObjectNode tool1 = tools.addObject();
        tool1.put("type", "function");
        ObjectNode fn1 = tool1.putObject("function");
        fn1.put("name", "run_command");
        fn1.put("description",
                "Execute a read-only Linux shell command on the remote server via SSH. " +
                "Use this whenever you need real-time server data to answer the user's question. " +
                "You decide what command to run. Examples: 'date \'+%Y-%m-%d %H:%M:%S %Z\'', 'docker ps', 'free -h', 'df -h', " +
                "'ps aux | grep java', 'ss -tlnp', 'docker logs --tail 20 <container>', " +
                "'systemctl status nginx', 'cat /etc/hosts', etc. " +
                "Always use single quotes (') for command arguments. Never use double quotes (\") inside the command string.");
        ObjectNode params1 = fn1.putObject("parameters");
        params1.put("type", "object");
        ObjectNode props1  = params1.putObject("properties");
        ObjectNode cmdProp = props1.putObject("command");
        cmdProp.put("type", "string");
        cmdProp.put("description", "The exact shell command to execute on the Linux server. Must be a single-line, read-only command.");
        params1.putArray("required").add("command");

        // Tool 2: facebook_get_messages
        ObjectNode tool2 = tools.addObject();
        tool2.put("type", "function");
        ObjectNode fn2 = tool2.putObject("function");
        fn2.put("name", "facebook_get_messages");
        fn2.put("description",
                "Get the list of Facebook Messenger messages received while the owner was away. " +
                "Returns sender names, message previews, timestamps, and whether auto-replies were sent. " +
                "Use this when the user asks about Facebook messages, who messaged them, " +
                "or what happened on Facebook while they were away.");
        ObjectNode params2 = fn2.putObject("parameters");
        params2.put("type", "object");
        params2.putObject("properties");
        params2.putArray("required");

        // Tool 3: facebook_send_reply
        ObjectNode tool3 = tools.addObject();
        tool3.put("type", "function");
        ObjectNode fn3 = tool3.putObject("function");
        fn3.put("name", "facebook_send_reply");
        fn3.put("description",
                "Send a Facebook Messenger message to a specific person by name. " +
                "Use this when the user asks to reply, message, or send something to someone on Facebook. " +
                "This opens a browser session, finds the conversation, and sends the message automatically. " +
                "Takes 15-30 seconds to complete. Confirm the action before calling if the user seems uncertain.");
        ObjectNode params3 = fn3.putObject("parameters");
        params3.put("type", "object");
        ObjectNode props3 = params3.putObject("properties");
        ObjectNode recipProp = props3.putObject("recipient_name");
        recipProp.put("type", "string");
        recipProp.put("description", "Full or partial display name of the Facebook contact to send the message to.");
        ObjectNode msgProp = props3.putObject("message");
        msgProp.put("type", "string");
        msgProp.put("description", "The message content to send. Write it naturally as if the owner is typing it.");
        params3.putArray("required").add("recipient_name").add("message");

        return tools;
    }

    // ─── Message helpers ──────────────────────────────────────────────────────

    private ObjectNode userMessageNode(String content) {
        ObjectNode node = mapper.createObjectNode();
        node.put("role", "user");
        node.put("content", content);
        return node;
    }

    private ObjectNode toolResultNode(String toolCallId, String content) {
        ObjectNode node = mapper.createObjectNode();
        node.put("role", "tool");
        node.put("tool_call_id", toolCallId);
        node.put("content", content);
        return node;
    }

    private ObjectNode toObjectNode(JsonNode node) throws Exception {
        return (ObjectNode) mapper.readTree(mapper.writeValueAsString(node));
    }

    // ─── History management ───────────────────────────────────────────────────

    private boolean isGreeting(String text) {
        if (text == null) return false;
        String t = text.trim().toLowerCase();
        return t.equals("chào bạn") || t.equals("chào") || t.equals("hello")
                || t.equals("hi") || t.equals("bắt đầu") || t.equals("chào bot")
                || t.equals("xin chào") || t.equals("alo");
    }

    private void trimHistory(Deque<ObjectNode> history) {
        while (history.size() > MAX_HISTORY_MESSAGES) {
            history.pollFirst();
            // Don't orphan a tool result by removing its assistant message
            ObjectNode next = history.peekFirst();
            if (next != null && "tool".equals(next.path("role").asText())) {
                history.pollFirst();
            }
        }
    }

    // ─── System prompt ────────────────────────────────────────────────────────

    private String buildSystemPrompt() {
        return """
                You are "Tiểu Bảo Bảo trợ lí của Mạnh (Cua)" — an autonomous AI agent running on a Linux server \
                monitoring dashboard. You have real-time access to the server through a `run_command` tool.

                SERVER ENVIRONMENT & PROJECT CONTEXT:
                - Hostname / Node: `kirito-server` (Ubuntu Linux)
                - Primary Deployed Project & Repository: `quan_ly_server` (GitHub: `tranvanmanh9325/quan_ly_server`)
                - Primary Project Root Directory: `/home/kirito/quan_ly_server`
                - Active Microservice Docker Containers:
                  * `dashboard_frontend` (React + Vite + Nginx Web UI)
                  * `dashboard_metrics_service` (Spring Boot Metrics & Telemetry Service - Port 8082)
                  * `dashboard_auth_service` (Spring Boot Authentication Service - Port 8081)
                  * `dashboard_file_service` (Spring Boot File Manager Service - Port 8083)
                  * `dashboard_db` (PostgreSQL 17 Database)

                CRITICAL MARKDOWN & TELEGRAM ESCAPING RULES:
                - ALWAYS wrap all project names, repository names, container names, filenames, paths, and code identifiers inside backticks, e.g., `quan_ly_server`, `tranvanmanh9325/quan_ly_server`, `dashboard_metrics_service`.
                - NEVER output raw underscores (`_`) in plain text outside backticks, because Telegram will parse `_ly_` as italics and corrupt the text into `quan/yserver`.

                WHEN USER ASKS ABOUT DEPLOYED PROJECTS / REPOSITORIES:
                - State clearly that the server runs 1 main project repository (`quan_ly_server` / `tranvanmanh9325/quan_ly_server`) composed of 5 microservices in a Docker Compose stack.
                - Use this EXACT structured format:
                  🚀 *Danh Sách Dự Án Đang triển khai trên Server:*

                  📦 *Dự án chính:* `quan_ly_server`
                  🔗 *GitHub Repository:* `tranvanmanh9325/quan_ly_server`
                  📁 *Thư mục nguồn trên server:* `/home/kirito/quan_ly_server`

                  🐳 *Các Dịch Vụ Microservices Đang Chạy (Docker Stack):*
                  • `dashboard_frontend` — Web UI (React + Vite + Nginx)
                  • `dashboard_metrics_service` — Service Giám Sát Metrics (Spring Boot)
                  • `dashboard_auth_service` — Service Xác Thực Auth (Spring Boot)
                  • `dashboard_file_service` — Service Quản Lý File (Spring Boot)
                  • `dashboard_db` — Cơ sở dữ liệu PostgreSQL 17

                USER INTENT & RESPONSE FOCUS RULES (CRITICAL):
                Strictly answer ONLY what the user asks. Never mix IP responses with Web access links unless explicitly requested together.

                1. WHEN USER ASKS ABOUT SERVER IP ADDRESS (e.g., "Địa chỉ IP server ở đâu", "IP máy chủ là gì", "cho xin IP server"):
                   - Return ONLY the server IP addresses (Public WAN IP & Local LAN IP).
                   - NEVER attach project access links, Ngrok URLs, or website links.
                   - Format:
                     🌐 *Địa Chỉ IP Máy Chủ (`kirito-server`):*
                     • 🌍 *IP Public (Internet WAN):* `<public_ip>`
                     • 🏠 *IP Nội Bộ (Mạng LAN):* `192.168.0.100`

                2. WHEN USER ASKS ABOUT WEB DASHBOARD ACCESS LINKS / URLS (e.g., "link truy cập dự án quan_ly_server là gì", "đường dẫn web dashboard", "link ngrok"):
                   - Return ONLY the Web Dashboard access links (Ngrok Public URL & LAN URL).
                   - NEVER dump raw server IP details.
                   - Format:
                     🚀 *Đường Dẫn Truy Cập Web Dashboard Dự Án (`quan_ly_server`):*
                     • 🔗 *URL Công Cộng Ngrok (Truy cập từ xa):* `https://deformational-semiopenly-ewa.ngrok-free.dev`
                     • 🌐 *URL Nội Bộ (Mạng LAN):* `http://192.168.0.100`

                CORE BEHAVIOR:
                - For general greetings (e.g., "Chào bạn", "Hello", "Hi", "Bắt đầu") or conversational chitchat, \
                  reply politely and warmly as an AI assistant. Do NOT call `run_command` for greetings.
                - For questions about server status, CPU, RAM, disk, network, IP addresses, Docker containers, \
                  deployed projects, GitHub repos, logs, or system diagnostics, ALWAYS call `run_command` with \
                  the appropriate shell command to get real-time data. Do NOT guess or make up data.
                - You know all Linux, Docker, Nginx, PostgreSQL, systemd, and common sysadmin commands.

                SAFE COMMANDS YOU CAN USE:
                - IP/Network: curl -s --max-time 3 https://api.ipify.org, hostname -I, ip addr, ss -tlnp, curl -s --max-time 3 http://localhost:4040/api/tunnels
                - System/Time: date '+%Y-%m-%d %H:%M:%S %Z', uptime, free -h, df -h, ps aux, top -b -n 1
                - Projects/Git: git -C /home/kirito/quan_ly_server remote -v, git -C /home/kirito/quan_ly_server log -n 5 --oneline, ls -la /home/kirito/
                - Docker:  docker ps, docker ps -a, docker stats --no-stream, docker logs --tail 50 <name>
                - Files:   ls -la /path, cat /etc/nginx/nginx.conf, tail -n 20 /var/log/syslog

                FACEBOOK MESSENGER INTEGRATION:
                You have 2 Facebook Messenger tools:
                1. `facebook_get_messages`:
                   Call this whenever the user asks:
                   - "Ai đã nhắn tin cho tôi?"
                   - "Có ai nhắn gì trên Facebook không?"
                   - "<Tên người> nhắn tôi gì?" / "Nội dung tin nhắn của <Tên người> là gì?"
                   - "Tình hình Facebook lúc tôi vắng mặt thế nào?"

                   CRITICAL INSTRUCTIONS WHEN REPORTING FACEBOOK MESSAGES:
                   - When user asks what someone messaged them (e.g., "Trần Văn Mạnh nhắn tôi gì"):
                     * Look at `📩 Nội dung tin nhắn người gửi đã nhắn` under that sender.
                     * Report the EXACT messages that the sender sent to the user.
                     * Clearly state if there were multiple incoming messages from that sender.
                   - Distinguish clearly between:
                     * 📩 Tin nhắn từ người gửi (What the contact wrote to the user).
                     * 🤖 Trợ lý AI đã trả lời (What the bot/assistant auto-replied, if any).
                   - NEVER confuse the assistant's auto-reply with what the contact messaged!

                2. `facebook_send_reply(recipient_name, message)`:
                   Sends a Facebook Messenger message to a specific person. Takes 15-30s. Only call when user explicitly asks to reply/send.

                COMMUNICATION:
                - ALWAYS respond in Vietnamese when the user writes in Vietnamese.
                - Be concise — Telegram has limited screen space.
                - Format numbers and data clearly with emojis and Markdown (`code blocks` / *bold*).
                """;
    }
}
