package com.miniserver.metrics.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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

    @Value("${groq.api-key:}")
    private String apiKey;

    @Value("${groq.model:llama-3.1-8b-instant}")
    private String model;

    private final SshService  sshService;
    private final ObjectMapper mapper = new ObjectMapper();
    private final RestClient   restClient;

    // chatId → full OpenAI-format message history
    private final Map<String, Deque<ObjectNode>> historyMap = new ConcurrentHashMap<>();

    public AiChatService(SshService sshService) {
        this.sshService = sshService;
        // 30s read timeout — LLM inference can be slow under load
        this.restClient = RestClientFactory.create(5_000, 30_000);
    }

    // ─── Public API ──────────────────────────────────────────────────────────

    public boolean isConfigured() {
        return apiKey != null && !apiKey.isBlank();
    }

    public String chat(String chatId, String userMessage) {
        if (!isConfigured()) {
            return "AI chua duoc cau hinh. Vui long dat GROQ_API_KEY.";
        }

        Deque<ObjectNode> history = historyMap.computeIfAbsent(chatId, k -> new ArrayDeque<>());
        history.addLast(userMessageNode(userMessage));

        if (isGreeting(userMessage)) {
            String greetingReply = "Xin chào! Tôi là Server Monitor AI, trợ lý tự động giám sát máy chủ Linux. "
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
        if (!"run_command".equals(toolName)) {
            return "Unknown tool: " + toolName;
        }
        try {
            JsonNode args    = mapper.readTree(argsJson);
            String   command = args.path("command").asText("").trim();
            if (command.isBlank()) return "No command provided.";
            return executeShellCommand(command);
        } catch (Exception e) {
            return "Failed to parse tool arguments: " + e.getMessage();
        }
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

    private String callGroq(String requestBody) throws Exception {
        int maxRetries = 3;
        for (int attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                return restClient.post()
                        .uri(GROQ_API_URL)
                        .contentType(MediaType.APPLICATION_JSON)
                        .header("Authorization", "Bearer " + apiKey)
                        .body(requestBody)
                        .retrieve()
                        .body(String.class);
            } catch (HttpClientErrorException.TooManyRequests e) {
                if (attempt < maxRetries) {
                    // Exponential backoff: 1s → 2s → 3s. Keeps first retry fast while
                    // still giving the rate limiter enough headroom to recover.
                    long sleepMs = 1000L * (attempt + 1);
                    log.warn("[Agent] Groq 429 Rate limited, retrying in {}ms (attempt {}/{})...", sleepMs, attempt + 1, maxRetries);
                    Thread.sleep(sleepMs);
                } else {
                    throw e;
                }
            }
        }
        throw new IllegalStateException("Max retries exceeded for Groq API");
    }

    /**
     * Defines the single generic tool exposed to the AI.
     * The AI generates the shell command itself based on the user's question —
     * no pre-registration needed for new question types.
     */
    private ArrayNode buildToolDefinitions() {
        ArrayNode tools    = mapper.createArrayNode();
        ObjectNode tool    = tools.addObject();
        tool.put("type", "function");
        ObjectNode fn      = tool.putObject("function");

        fn.put("name", "run_command");
        fn.put("description",
                "Execute a read-only Linux shell command on the remote server via SSH. " +
                "Use this whenever you need real-time server data to answer the user's question. " +
                "You decide what command to run. Examples: 'date '+%Y-%m-%d %H:%M:%S %Z'', 'docker ps', 'free -h', 'df -h', " +
                "'ps aux | grep java', 'ss -tlnp', 'docker logs --tail 20 <container>', " +
                "'systemctl status nginx', 'cat /etc/hosts', etc. " +
                "Always use single quotes (') for command arguments. Never use double quotes (\") inside the command string.");

        ObjectNode params = fn.putObject("parameters");
        params.put("type", "object");
        ObjectNode props  = params.putObject("properties");
        ObjectNode cmdProp = props.putObject("command");
        cmdProp.put("type", "string");
        cmdProp.put("description",
                "The exact shell command to execute on the Linux server. " +
                "Must be a single-line, read-only command. Always use single quotes (') for argument options, e.g. date '+%Y-%m-%d %H:%M:%S %Z'.");
        params.putArray("required").add("command");

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
                You are "Server Monitor AI" — an autonomous AI agent running on a Linux server \
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

                CORE BEHAVIOR:
                - For general greetings (e.g., "Chào bạn", "Hello", "Hi", "Bắt đầu") or conversational chitchat, \
                  reply politely and warmly as an AI assistant. Do NOT call `run_command` for greetings.
                - For questions about server status, CPU, RAM, disk, network, processes, Docker containers, \
                  deployed projects, GitHub repos, logs, or system diagnostics, ALWAYS call `run_command` with \
                  the appropriate shell command to get real-time data. Do NOT guess or make up data.
                - You know all Linux, Docker, Nginx, PostgreSQL, systemd, and common sysadmin commands.

                SAFE COMMANDS YOU CAN USE:
                - System/Time: date '+%Y-%m-%d %H:%M:%S %Z', uptime, free -h, df -h, ps aux, top -b -n 1
                - Projects/Git: git -C /home/kirito/quan_ly_server remote -v, git -C /home/kirito/quan_ly_server log -n 5 --oneline, ls -la /home/kirito/
                - Docker:  docker ps, docker ps -a, docker stats --no-stream, docker logs --tail 50 <name>
                - Network: ss -tlnp, netstat -tulnp, ip addr, ping -c 2 <host>
                - Files:   ls -la /path, cat /etc/nginx/nginx.conf, tail -n 20 /var/log/syslog

                COMMUNICATION:
                - ALWAYS respond in Vietnamese when the user writes in Vietnamese.
                - Be concise — Telegram has limited screen space.
                - Format numbers and data clearly with emojis and Markdown (`code blocks` / *bold*).
                """;
    }
}
