-- ─── Processed Telegram Updates (Deduplication Lock) ─────────────────────────
-- Stores claimed update_ids to prevent duplicate message processing across multi-node/dev+prod deployments.
CREATE TABLE IF NOT EXISTS processed_telegram_updates (
    update_id    BIGINT PRIMARY KEY,
    processed_at TIMESTAMP NOT NULL DEFAULT now()
);

-- ─── Telegram Node Priority Lock ──────────────────────────────────────────────
-- Allows Local Dev environment to claim 100% priority over Production node.
CREATE TABLE IF NOT EXISTS telegram_active_node (
    id             INT PRIMARY KEY CHECK (id = 1),
    node_name      VARCHAR(50) NOT NULL,
    last_heartbeat TIMESTAMP NOT NULL DEFAULT now()
);
