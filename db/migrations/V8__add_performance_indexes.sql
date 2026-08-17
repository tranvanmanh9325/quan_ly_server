-- Migration V8: Add performance B-Tree indexes for fast range queries and cleanup
-- Target tables: server_metrics, facebook_known_threads, processed_telegram_updates

-- 1. Index on server_metrics(timestamp DESC) for O(log N) telemetry chart queries & cleanup
CREATE INDEX IF NOT EXISTS idx_server_metrics_timestamp 
ON server_metrics (timestamp DESC);

-- 2. Functional index on LOWER(sender_name) for fast thread & profile resolution
CREATE INDEX IF NOT EXISTS idx_fb_known_threads_sender 
ON facebook_known_threads (LOWER(sender_name));

-- 3. Index on processed_at for telegram update retention cleanup
CREATE INDEX IF NOT EXISTS idx_processed_telegram_processed_at 
ON processed_telegram_updates (processed_at);
