-- V16: Cognitive Architecture v2.0 — Episodic Memory + Prospective Memory
-- Phase 4: Episodic Memory (Hippocampal model) — tach Su kien khoi Kien thuc
-- Phase 5: Prospective Memory — nho viec can lam + proactive intelligence

-- Phase 4: Episodic Memory (Hippocampus-inspired)
-- Stores SPECIFIC events with timestamp + context (like hippocampal episodic memory).
-- Separate from agent_lessons (semantic memory = abstract knowledge).
CREATE TABLE IF NOT EXISTS agent_episodes (
    id              SERIAL PRIMARY KEY,
    event_summary   TEXT            NOT NULL,
    event_type      VARCHAR(50)     NOT NULL DEFAULT 'incident',
    severity        VARCHAR(20)     NOT NULL DEFAULT 'low',
    salience_score  DECIMAL(4,3)    NOT NULL DEFAULT 0.500,
    full_context    TEXT,
    tags            TEXT[],
    occurred_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_agent_episodes_active_salience
    ON agent_episodes (is_active, salience_score DESC, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_episodes_severity
    ON agent_episodes (severity, is_active, occurred_at DESC);

-- Phase 5A: Prospective Memory (Prefrontal + Hippocampus)
-- "Remember to do X later" — pending tasks injected into next conversation context.
CREATE TABLE IF NOT EXISTS agent_pending_tasks (
    id              SERIAL PRIMARY KEY,
    task_summary    TEXT            NOT NULL,
    created_by_msg  TEXT,
    remind_at       TIMESTAMPTZ,
    remind_turns    INTEGER         DEFAULT 3,
    turns_elapsed   INTEGER         DEFAULT 0,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_pending_tasks_status
    ON agent_pending_tasks (status, remind_at);

-- Phase 5B: Proactive Scan Results (Curiosity-driven intelligence)
-- Records last known state of proactive health checks to detect changes + cooldown.
CREATE TABLE IF NOT EXISTS agent_proactive_checks (
    check_key       VARCHAR(100)    PRIMARY KEY,
    last_value      TEXT,
    last_alerted    TIMESTAMPTZ,
    alert_count     INTEGER         NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
