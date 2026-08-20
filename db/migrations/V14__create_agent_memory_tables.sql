-- V14: Agent Memory Tables (Self-Improving AI Agent)
-- Provides persistent Episodic Memory (corrections/events history)
-- and Procedural Memory (extracted lessons injected into system prompt).

-- ─── Procedural Memory: "Bài học" đã được xác nhận ────────────────────────
-- Bot tự rút ra bài học từ mỗi lần bị sửa lỗi rồi inject vào system prompt.
CREATE TABLE IF NOT EXISTS agent_lessons (
    id              SERIAL PRIMARY KEY,
    trigger_pattern TEXT            NOT NULL,           -- Dạng lỗi/tình huống kích hoạt bài học
    lesson_text     TEXT            NOT NULL,           -- Nội dung bài học (ngắn gọn, actionable)
    event_type      VARCHAR(50)     NOT NULL DEFAULT 'correction', -- correction | new_knowledge | success_pattern
    confidence      DECIMAL(3, 2)  NOT NULL DEFAULT 0.70, -- 0.00 → 1.00
    usage_count     INTEGER         NOT NULL DEFAULT 0,  -- Tăng mỗi lần lesson này được đọc/inject
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

-- Lấy top lessons nhanh
CREATE INDEX IF NOT EXISTS idx_agent_lessons_active_confidence
    ON agent_lessons (is_active, confidence DESC, usage_count DESC);

-- ─── Episodic Memory: Lịch sử các sự kiện học hỏi ────────────────────────
-- Ghi lại chi tiết từng lần bị sửa, mỗi kiến thức mới, hoặc pattern thành công.
CREATE TABLE IF NOT EXISTS agent_memories (
    id                  SERIAL PRIMARY KEY,
    event_type          VARCHAR(50)  NOT NULL,   -- correction | new_knowledge | success_pattern
    user_input          TEXT         NOT NULL,   -- Tin nhắn gốc của user
    original_response   TEXT,                    -- Câu trả lời SAI của bot (nếu là correction)
    corrected_response  TEXT,                    -- Câu trả lời ĐÚNG (user cung cấp hoặc AI tự sửa)
    lesson_id           INTEGER REFERENCES agent_lessons(id) ON DELETE SET NULL,
    context_snapshot    TEXT,                    -- JSON dump 5 turns gần nhất (để phân tích)
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_event_type
    ON agent_memories (event_type, created_at DESC);
