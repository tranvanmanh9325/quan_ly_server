-- ─── TikTok Social Automation & Streak Keeper Tables ─────────────────────────

-- Single-row config table (id always = 1)
CREATE TABLE IF NOT EXISTS tiktok_config (
    id                      BIGINT PRIMARY KEY CHECK (id = 1),
    enabled                 BOOLEAN NOT NULL DEFAULT false,
    streak_enabled          BOOLEAN NOT NULL DEFAULT true,
    streak_schedule_hour    INTEGER NOT NULL DEFAULT 9,
    streak_targets          TEXT NOT NULL DEFAULT '[]',
    streak_message_template TEXT NOT NULL DEFAULT 'Video giữ chuỗi hôm nay nè! 🔥',
    streak_send_type        TEXT NOT NULL DEFAULT 'video',
    threshold               INTEGER NOT NULL DEFAULT 3,
    scan_interval_minutes   INTEGER NOT NULL DEFAULT 3,
    idle_timeout_minutes    INTEGER NOT NULL DEFAULT 1,
    human_session_minutes   INTEGER NOT NULL DEFAULT 5,
    cooldown_minutes        INTEGER NOT NULL DEFAULT 60,
    cookies_json            TEXT NOT NULL DEFAULT '',
    custom_message          TEXT NOT NULL DEFAULT '',
    last_status             TEXT NOT NULL DEFAULT 'Tắt',
    last_check_at           TIMESTAMP,
    last_streak_run_at      TIMESTAMP,
    created_at              TIMESTAMP NOT NULL DEFAULT now(),
    updated_at              TIMESTAMP NOT NULL DEFAULT now()
);

-- Seed single row if not exists
INSERT INTO tiktok_config (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Activity and Streak Dispatch History
CREATE TABLE IF NOT EXISTS tiktok_replies (
    id              SERIAL PRIMARY KEY,
    target_type     TEXT NOT NULL DEFAULT 'dm', -- 'dm' | 'streak_video' | 'streak_msg'
    recipient_name  TEXT NOT NULL,
    recipient_id    TEXT,
    received_text   TEXT,
    reply_text      TEXT,
    video_url       TEXT,
    status          TEXT NOT NULL DEFAULT 'sent', -- 'sent' | 'pending' | 'failed'
    created_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tiktok_replies_created_at ON tiktok_replies (created_at DESC);
