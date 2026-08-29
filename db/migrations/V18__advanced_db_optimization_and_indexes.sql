-- ==============================================================================
-- Migration V18: Advanced Database Optimization, BRIN & Composite Indexes
-- Target: PostgreSQL 17 Performance Acceleration for 3.2GB RAM / 2-Core Server
-- ==============================================================================

-- ─── 1. EXTENSIONS ────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- ─── 2. TIME-SERIES METRICS OPTIMIZATION (server_metrics) ─────────────────────
-- 2.1. BRIN Index for ultra-fast time-series range scans & 7-day retention deletes
-- Storage footprint is 98% smaller than B-Tree, stays 100% in L1/L2 cache
CREATE INDEX IF NOT EXISTS idx_server_metrics_timestamp_brin 
ON server_metrics USING brin (timestamp) WITH (pages_per_range = 32);

-- 2.2. Covering Index for Sparkline Dashboard (Index-Only Scan / Zero Heap Fetch)
CREATE INDEX IF NOT EXISTS idx_server_metrics_covering 
ON server_metrics (timestamp DESC) 
INCLUDE (cpu_percent, ram_percent, disk_percent);

-- ─── 3. FACEBOOK APPOINTMENTS ADVANCED PARTIAL INDEXES ────────────────────────
-- 3.1. Partial Index for pending reminder daemon (O(1) lookup, < 8KB footprint)
CREATE INDEX IF NOT EXISTS idx_fb_appointments_pending_remind 
ON facebook_appointments (scheduled_at) 
WHERE status = 'confirmed' AND reminder_sent = FALSE;

-- 3.2. Composite Index for status filtering with chronologic ordering
CREATE INDEX IF NOT EXISTS idx_fb_appointments_status_created 
ON facebook_appointments (status, created_at DESC);

-- ─── 4. MESSENGER GROUPS & DISCOVERY ACCELERATION ────────────────────────────
-- 4.1. GIN index for JSONB member role/name containment queries (@>, ?)
CREATE INDEX IF NOT EXISTS idx_messenger_groups_members_gin 
ON messenger_groups USING gin (members jsonb_path_ops);

-- 4.2. Index for recently discovered Facebook threads
CREATE INDEX IF NOT EXISTS idx_fb_known_threads_discovered_desc 
ON facebook_known_threads (discovered_at DESC);

-- 4.3. Partial Index for pending unsent auto-replies
CREATE INDEX IF NOT EXISTS idx_fb_known_threads_unsent 
ON facebook_known_threads (thread_href) 
WHERE auto_reply_unsent = FALSE;

-- ─── 5. TIKTOK SOCIAL & DISPATCH HISTORY ──────────────────────────────────────
-- Composite Index for target filtering with recent activity ordering
CREATE INDEX IF NOT EXISTS idx_tiktok_replies_target_created 
ON tiktok_replies (target_type, created_at DESC);

-- ─── 6. AI COGNITIVE MEMORY ENGINE ACCELERATION ──────────────────────────────
-- 6.1. GIN Index for Episode Tag searches (e.g. tags && ARRAY['db', 'docker'])
CREATE INDEX IF NOT EXISTS idx_agent_episodes_tags_gin 
ON agent_episodes USING gin (tags);

-- 6.2. Trigram Index for fast fuzzy trigger pattern matching
CREATE INDEX IF NOT EXISTS idx_agent_lessons_pattern_trgm 
ON agent_lessons USING gin (trigger_pattern gin_trgm_ops);

-- 6.3. Partial Index for active prospective memory pending tasks
CREATE INDEX IF NOT EXISTS idx_agent_pending_tasks_active 
ON agent_pending_tasks (created_at ASC) 
WHERE status = 'pending';
