# Autonomous AI Agent ("Tiểu Bảo Bảo") & 9Router Ecosystem

A comprehensive technical reference for the autonomous AI sysadmin assistant ("Tiểu Bảo Bảo"), the 9Router Multi-Provider LLM Pool (Groq + OpenRouter), Telegram Bot automation, and Facebook Messenger End-to-End Encrypted (E2EE) automation engine.

---

## 🌟 Overview & System Topology

```mermaid
flowchart TD
    subgraph InboundEvents["Inbound Multi-Channel Triggers"]
        TGEvent["Telegram Chat Message / Command"]
        FBEvent["Facebook Messenger Unread Message"]
        TTEvent["TikTok DM / Daily Streak Deadline"]
        ApptEvent["1-Hour Appointment Scheduled Trigger"]
    end

    subgraph CoreAgentService["AI Agent Microservice (FastAPI :8084)"]
        direction TB

        subgraph ReasoningLayer["🧠 Autonomous Agent Brain ('Tiểu Bảo Bảo')"]
            BLUF["Pyramid Principle (BLUF Engine)\nLine 1: Direct Executive Summary"]
            ContextCompactor["Active Turn Context Compactor\nProgressive Tool Output Compression (<3,500 chars)"]
            LoopBreaker["Anti-Loop Stagnation Circuit Breaker\nIteration >= 4 -> Force tool_choice='none'"]
            MemoryBrain["AgentMemoryService\nLessons, Preferences & Cross-Session Memory"]
        end

        subgraph RouterLayer["🔀 9Router Multi-Provider Key Pool & RTK"]
            RTK["Real-Time Token Compressor (RTK)\nJSON Compact | ANSI Strip | Log Sampler"]
            Tier1["Tier 1: Groq Multi-Key Pool\n(openai/gpt-oss-120b)\nRound-Robin + 60s 429 Cooldown"]
            Tier2["Tier 2: OpenRouter Key Pool\n(nvidia/nemotron-3-super-120b)\nZero-Downtime Auto-Failover"]
        end

        subgraph FormattingLayer["🎨 TelegramFormatter Engine"]
            TableToCards["Table-to-Card Transformer\n|---|---| -> Visual Emoji Cards"]
            HTMLSanitizer["Telegram HTML Sanitizer & Tag Balancer\n<b>, <i>, <code>, <pre>, <blockquote>"]
            VietnameseNormalizer["Vietnamese Typography & Spelling Normalizer\nFixes 'KẾ THÚC' -> 'KẾT LUẬN', Strips Leaked Tokens"]
            Chunker["Smart Message Chunker\nParagraph-safe boundary split <= 4,000 chars"]
        end

        subgraph AutomationEngines["🤖 Platform Automation Engines"]
            PlaywrightFB["Facebook E2EE Playwright Automation\n6-Digit PIN Decryption | Auto-Reply | Unsend"]
            PlaywrightTT["TikTok Playwright Automation\nAutomated DM Scan & Daily Streak Keeper"]
            ApptService["Proactive Appointment Reminder Dispatcher"]
        end
    end

    subgraph StorageAndHost["External Services & Persistent Storage"]
        PostgresDB[("PostgreSQL 17 Alpine\nrtk_stats, memories, threads")]
        TargetHost["🖥️ Target Linux Host (kirito-server)\nPhysical Location: Định Công, Hoàng Mai, Hà Nội"]
    end

    InboundEvents --> ReasoningLayer
    ReasoningLayer <--> RouterLayer
    RouterLayer --> Tier1
    Tier1 -.->|429 / Quota Exhaustion| Tier2
    RouterLayer <--> RTK
    RTK <--> PostgresDB

    ReasoningLayer ==>|AsyncSSH Tool Calls| TargetHost
    ReasoningLayer --> FormattingLayer
    FormattingLayer --> TelegramOutbound["Telegram In-App Delivery"]

    FBEvent --> PlaywrightFB
    TTEvent --> PlaywrightTT
    ApptEvent --> ApptService
    ApptService --> TelegramOutbound
    PlaywrightFB <--> PostgresDB
    MemoryBrain <--> PostgresDB
```

---

## 1. Pyramid Principle & BLUF Thinking Flowchart

```mermaid
flowchart TD
    Start(["Incoming Sysadmin Question"]) --> Step1["🎯 BƯỚC 1: KẾT LUẬN TRỰC DIỆN (BLUF - Bottom Line Up Front)\n• Dòng 1 luôn đưa ra câu trả lời dứt khoát, trực diện vào vấn đề\n• Ví dụ: 'Dạ vâng anh Mạnh, lệnh sudo apt update ĐÃ ĐƯỢC CHẠY sáng nay (06:00 ICT)...'"]
    
    Step1 --> Step2["📊 BƯỚC 2: BẰNG CHỨNG & PHÂN TÍCH ĐÃ XÁC THỰC (Cards Layout)\n• Tổ chức dữ liệu thành các thẻ Card với Emoji đại diện (📌, 🕒, ✅, 🔍)\n• Trích dẫn 1-3 dòng log quan trọng nhất, tuyệt đối không dump toàn bộ log\n• Chuyển đổi toàn bộ cú pháp bảng Markdown thành dạng thẻ trực quan"]
    
    Step2 --> Step3["💡 BƯỚC 3: GIẢI THÍCH SÚC TÍCH & HƯỚNG DẪN HÀNH ĐỘNG\n• Giải thích nguyên lý kỹ thuật đằng sau (vd: Systemd Timer thay thế cron.daily)\n• Khuyến nghị hành động tiếp theo hoặc lưu ý quan trọng"]
    
    Step3 --> Finish(["Phản hồi hoàn chỉnh, sắc nét trên Telegram"])
```

---

## 2. Telegram Native Formatter Pipeline (`TelegramFormatter`)

```mermaid
flowchart LR
    RawLLM["Raw LLM Output Text"] --> Step1["1. Typography & Spelling Normalization\n'KẾ THÚC' -> 'KẾT LUẬN'\n'06:00 h' -> '06:00'\nUnicode '-' -> ASCII '-'"]
    
    Step1 --> Step2["2. Code Token Preservation\nExtract ```code``` -> TGTOKENCODEBLOCK{i}END\nExtract `code` -> TGTOKENINLINECODE{i}END"]
    
    Step2 --> Step3["3. Table-to-Card Conversion\nDetect | Header | -> <b>Header:</b> Value"]
    
    Step3 --> Step4["4. HTML Tag Sanitization\nEscape raw <, >, &\nConvert **, *, _, ~~ to <b>, <i>, <s>"]
    
    Step4 --> Step5["5. Restore Code Blocks\nRe-inject <pre><code> and <code> tags"]
    
    Step5 --> Step6["6. HTML Tag Balancing & Chunking\nAuto-balance unclosed tags\nSplit messages > 4,000 chars"]
    
    Step6 --> OutputHTML["Telegram-Compliant HTML"]
```

---

## 3. 9Router Multi-Provider Key Pool State Machine

```mermaid
stateDiagram-v2
    [*] --> Tier1_GroqActive

    state Tier1_GroqActive {
        [*] --> KeyRoundRobin
        KeyRoundRobin --> KeySelected: Pick Next Available Key
        KeySelected --> ExecuteRequest: HTTP POST api.groq.com
        
        ExecuteRequest --> RequestSuccess: HTTP 200 OK
        RequestSuccess --> KeyRoundRobin: Increment usage counter
        
        ExecuteRequest --> KeyRateLimited: HTTP 429 Rate Limit
        KeyRateLimited --> Cooldown60s: available_at = now + 60s
        Cooldown60s --> KeyRoundRobin: Skip during cooldown
    }

    Tier1_GroqActive --> Tier2_OpenRouterFailover: All Groq Keys Exhausted / in Cooldown

    state Tier2_OpenRouterFailover {
        [*] --> OpenRouterKeySelection
        OpenRouterKeySelection --> ExecuteOpenRouter: HTTP POST openrouter.ai/api
        ExecuteOpenRouter --> OpenRouterSuccess: HTTP 200 OK
        ExecuteOpenRouter --> OpenRouterFallback: Try Next Fallback Key
    }

    Tier2_OpenRouterFailover --> Tier1_GroqActive: Groq Cooldown Expires (Auto-Recovery)
```

---

## 4. Real-Time Token Compressor (RTK) Data Pipeline

```mermaid
flowchart TD
    RawInput["Raw Tool Output / Terminal Log Stream\n(10,000+ chars, JSON, ANSI codes)"] --> Stage1["1. JSON Compaction\nMinify whitespace & indentation"]
    Stage1 --> Stage2["2. Strip ANSI Escapes\nRemove terminal color and cursor codes"]
    Stage2 --> Stage3["3. Timestamp Compactor\nCondense verbose ISO timestamps"]
    Stage3 --> Stage4["4. Repetitive Divider Compactor\n80 dashes -> 6 dashes"]
    Stage4 --> Stage5["5. Head-Tail Log Sampling\nKeep top 3 header lines + tail 2 lines + omit notice"]
    Stage5 --> Stage6["6. Hard Cap Boundary\nCap maximum output length at threshold"]
    Stage6 --> CompressedOutput["Compressed Payload (40–85% token volume reduction)"]
    CompressedOutput --> PersistDB["Persist Savings to PostgreSQL table: rtk_stats"]
```

---

## 5. Active Context Compactor & Anti-Loop Circuit Breaker

```mermaid
flowchart TD
    TurnStart["Agent Reasoning Turn Start"] --> CheckLoop{"Command already executed\nin current turn?"}
    
    CheckLoop -- Yes --> InjectDupNotice["Block Execution\nInject directive: 'Lệnh đã chạy, hãy tổng hợp câu trả lời'"]
    CheckLoop -- No --> ExecuteTool["Execute AsyncSSH Tool"]
    
    InjectDupNotice --> IterationCheck{"Current Iteration?"}
    ExecuteTool --> IterationCheck
    
    IterationCheck -- "Iteration < 3" --> CompactContext["_build_compact_messages_for_llm:\n• Retain full detail for 2 latest tools\n• Collapse older tools to 2-line summaries\n• Cap payload < 3,500 chars (Anti-HTTP 413)"]
    
    IterationCheck -- "Iteration == 3" --> InjectSynthDirective["Inject Synthesis Warning:\n'Đã thu thập đủ thông tin, dừng gọi tool và trả lời'"]
    
    IterationCheck -- "Iteration >= 4" --> ForceNoTools["Circuit Breaker Triggered:\nForce tool_choice='none'"]
    
    CompactContext --> NextLLMCall["LLM Inference Call"]
    InjectSynthDirective --> NextLLMCall
    ForceNoTools --> GracefulSynthesis["Graceful Final Synthesis Pass"]
    
    NextLLMCall --> HasTools{"Model calls more tools?"}
    HasTools -- Yes --> TurnStart
    HasTools -- No --> DeliverReply["Format & Deliver Answer"]
    GracefulSynthesis --> DeliverReply
```

---

## 6. Facebook Messenger E2EE Automation & Unsend Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Friend as 👤 Facebook Friend
    actor Owner as 👤 Anh Mạnh (Owner)
    participant FB as 💬 Messenger E2EE Web
    participant Bot as 🤖 Playwright Chromium
    participant DB as 🗄️ PostgreSQL 17
    participant TG as 📱 Telegram Bot

    Friend->>FB: Sends Encrypted Message (E2EE)
    Bot->>FB: Periodic Scan Cycle (Playwright)
    
    alt Encrypted PIN Challenge Detected
        Bot->>FB: Enter 6-digit PIN into E2EE keypad
        FB-->>Bot: Decrypt & display conversation history
    end

    Bot->>DB: Check thread state in facebook_known_threads
    
    alt Owner is Away & No Previous Auto-Reply
        Bot->>FB: Send Absence Notice: "Chào bạn, tôi là Tiểu Bảo Bảo..."
        Bot->>DB: Save auto_reply_text & set auto_reply_unsent = FALSE
        Bot->>TG: Notify Owner: "Đã gửi tin nhắn vắng mặt cho bạn [Tên]"
    end

    Note over Owner,FB: Human Owner responds directly or via Telegram /reply
    Owner->>FB: "Chào em, anh vừa online đây!"
    
    Bot->>FB: Next Scan Cycle: Detects human message (is_auto = False)
    Bot->>DB: Query: auto_reply_unsent == FALSE?
    
    alt Needs Unsend
        Bot->>FB: Locate absence message bubble
        Bot->>FB: Hover -> Click '⋮' -> 'Thu hồi' -> 'Thu hồi với mọi người' -> 'Gỡ'
        FB-->>Bot: Absence message deleted for everyone
        Bot->>DB: Update auto_reply_unsent = TRUE
        Bot->>TG: Proactive Alert: "Đã tự động thu hồi tin nhắn vắng mặt trên Facebook"
    end
```

---

## 7. TikTok Streak Keeper & DM Automation Flowchart

```mermaid
flowchart TD
    StartTikTok["TikTok Scheduled Scanner Loop (Every 3 min)"] --> VNCCheck{"Active Live noVNC Session?"}
    VNCCheck -- Yes --> Skip["Skip cycle to avoid browser lock contention"]
    VNCCheck -- No --> LoadConfig["Load TikTok Config & Streak Registry from DB"]
    
    LoadConfig --> DMScan{"DM Auto-Reply Enabled?"}
    DMScan -- Yes --> ScanInbox["Scan unread TikTok messages"]
    ScanInbox --> ReplyDMs["Generate contextual AI replies & send"]
    DMScan -- No --> StreakCheck
    ReplyDMs --> StreakCheck
    
    StreakCheck{"Daily Streak Keeper Enabled?"}
    StreakCheck -- Yes --> CheckDeadlines{"Streak interaction sent today?"}
    CheckDeadlines -- No --> SendStreak["Navigate to friends list -> Send daily interaction/emoji"]
    SendStreak --> UpdateDB["Update last_sent_time & streak_count in tiktok_streaks"]
    UpdateDB --> NotifyTG["Send Telegram confirmation: 'Đã duy trì streak TikTok thành công'"]
    CheckDeadlines -- Yes --> EndLoop(["Wait for next scheduled cycle"])
    StreakCheck -- No --> EndLoop
```

---

## 8. Agent Long-Term Self-Learning Memory Engine

```mermaid
flowchart LR
    Interaction["User Feedback / Correction\n('Sai rồi', 'Ở Hà Nội mà', 'Nhớ lịch này')"] --> AgentParser["AiAgent Feedback Analyzer"]
    
    AgentParser --> MemoryTypes{"Memory Classification"}
    
    MemoryTypes -->|Factual Rules & Fixes| Lessons["ai_agent_lessons\n• category: devops/location\n• lesson: 'Server đặt tại Định Công, Hà Nội'\n• confidence score"]
    
    MemoryTypes -->|User Custom Preferences| Preferences["ai_agent_preferences\n• preference_key: 'addressing'\n• value: 'anh Mạnh / em'"]
    
    MemoryTypes -->|Scheduled Reminders| Tasks["ai_scheduled_tasks\n• appointment_time\n• 1-hour proactive alert"]
    
    Lessons --> MemoryDB[("PostgreSQL 17\nPersistent Brain")]
    Preferences --> MemoryDB
    Tasks --> MemoryDB
    
    MemoryDB -.->|Dynamic Injection on Startup| SystemPrompt["System Prompt (Ground Truth & Lessons Block)"]
    SystemPrompt ==>|Governs| FutureDecisions["Next AI Turn Decisions & Answers"]
```

---

## 9. Unit Testing & Verification

Run the test suite inside the container:
```bash
docker exec dashboard_ai_agent python -m unittest discover -v -s /app/tests
```

**Test Coverage Summary:**
- `test_telegram_formatter.py` (11 tests): Markdown tables to cards, tag balancing, HTML sanitization, typography normalization, multilingual slip filter.
- `test_agent_loop_breaker.py` (2 tests): Context compaction and synthesis directive injection.
