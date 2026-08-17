-- ─── Messenger Groups Table ──────────────────────────────────────────────────
-- Stores group chat metadata and member snapshots discovered during scan cycles.
-- Enables AI Agent to answer "list groups" and "get group members" queries.
CREATE TABLE IF NOT EXISTS messenger_groups (
    id              SERIAL PRIMARY KEY,
    thread_href     TEXT UNIQUE NOT NULL,
    group_name      TEXT NOT NULL DEFAULT 'Nhóm không tên',
    member_count    INT NOT NULL DEFAULT 0,
    members         JSONB NOT NULL DEFAULT '[]',   -- [{name, role, profile_url}]
    last_scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messenger_groups_href   ON messenger_groups(thread_href);
CREATE INDEX IF NOT EXISTS idx_messenger_groups_name   ON messenger_groups(group_name);
CREATE INDEX IF NOT EXISTS idx_messenger_groups_scanned ON messenger_groups(last_scanned_at DESC);
