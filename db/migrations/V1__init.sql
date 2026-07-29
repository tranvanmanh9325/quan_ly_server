-- Initial schema: server_metrics + telegram_config
-- All tables defined here from the start (project not yet in production).

-- ─── Server Metrics ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS server_metrics (
    id           BIGSERIAL          PRIMARY KEY,
    timestamp    TIMESTAMP NOT NULL,
    cpu_percent  DOUBLE PRECISION,
    ram_percent  DOUBLE PRECISION,
    disk_percent DOUBLE PRECISION
);

-- ─── Telegram Bot Config ──────────────────────────────────────────────────────
-- Single-row config table (id always = 1), enforced by CHECK constraint.
CREATE TABLE IF NOT EXISTS telegram_config (
    id               BIGINT    PRIMARY KEY CHECK (id = 1),
    bot_token        TEXT      NOT NULL DEFAULT '',
    chat_id          TEXT      NOT NULL DEFAULT '',
    enabled          BOOLEAN   NOT NULL DEFAULT false,
    cpu_threshold    INTEGER   NOT NULL DEFAULT 80,
    ram_threshold    INTEGER   NOT NULL DEFAULT 85,
    disk_threshold   INTEGER   NOT NULL DEFAULT 90,
    cooldown_minutes INTEGER   NOT NULL DEFAULT 15,
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now()
);

-- Seed the single config row so UPDATE always works (no INSERT needed from app)
INSERT INTO telegram_config (id) VALUES (1) ON CONFLICT DO NOTHING;
