-- ─── Facebook Messenger Config ───────────────────────────────────────────────
-- Single-row config table (id always = 1), enforced by CHECK constraint.
CREATE TABLE IF NOT EXISTS facebook_config (
    id               BIGINT    PRIMARY KEY CHECK (id = 1),
    enabled          BOOLEAN   NOT NULL DEFAULT false,
    threshold        INTEGER   NOT NULL DEFAULT 5,
    cooldown_minutes INTEGER   NOT NULL DEFAULT 120,
    cookies_json     TEXT      NOT NULL DEFAULT '',
    custom_message   TEXT      NOT NULL DEFAULT '',
    last_status      TEXT      NOT NULL DEFAULT 'Tắt',
    last_check_at    TIMESTAMP,
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now()
);

-- Seed single row
INSERT INTO facebook_config (id) VALUES (1) ON CONFLICT DO NOTHING;
