-- ─── Facebook Known Threads ──────────────────────────────────────────────────
-- Stores discovered Messenger thread URLs across scan cycles.
-- Enables the scanner to check specific threads directly without relying
-- on the sidebar DOM (which is inaccessible in E2EE headless mode).
CREATE TABLE IF NOT EXISTS facebook_known_threads (
    thread_href       TEXT        PRIMARY KEY,
    sender_name       TEXT        NOT NULL DEFAULT '',
    last_checked_at   TIMESTAMPTZ,
    -- Hash of last seen incoming messages — used to detect new messages between scans
    -- and avoid re-replying when no new messages have arrived since the last reply.
    last_msg_hash     TEXT        NOT NULL DEFAULT '',
    discovered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
