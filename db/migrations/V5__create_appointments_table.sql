-- ─── Facebook Appointments Table ──────────────────────────────────────────
-- Stores appointment / scheduling intents detected from Facebook Messenger.
-- Used to manage user confirmations, prevent duplicate interactive prompts,
-- and provide AI Agent schedule tracking.
CREATE TABLE IF NOT EXISTS facebook_appointments (
    id                   SERIAL PRIMARY KEY,
    thread_href          TEXT NOT NULL DEFAULT '',
    sender_name          TEXT NOT NULL DEFAULT '',
    original_message     TEXT NOT NULL,
    msg_hash             TEXT NOT NULL,
    summary              TEXT NOT NULL,
    proposed_time        TEXT NOT NULL,
    location             TEXT DEFAULT '',
    confidence           VARCHAR(20) NOT NULL DEFAULT 'high',
    status               VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending', 'confirmed', 'dismissed', 'replied'
    telegram_message_id  BIGINT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fb_appointments_msg_hash ON facebook_appointments(msg_hash);
CREATE INDEX IF NOT EXISTS idx_fb_appointments_status ON facebook_appointments(status);
CREATE INDEX IF NOT EXISTS idx_fb_appointments_created_at ON facebook_appointments(created_at DESC);
