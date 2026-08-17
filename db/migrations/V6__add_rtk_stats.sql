-- ─── 9Router RTK Compressor Persistent Stats ──────────────────────────────
-- Single-row singleton table. Upserted on every persist cycle.
-- Ensures RTK token savings accumulate across container restarts.
CREATE TABLE IF NOT EXISTS rtk_stats (
    id                  INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),   -- Enforces singleton
    total_chars_saved   BIGINT NOT NULL DEFAULT 0,
    total_compressions  BIGINT NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the single row so UPSERT (ON CONFLICT DO UPDATE) always has a target
INSERT INTO rtk_stats (id, total_chars_saved, total_compressions)
VALUES (1, 0, 0)
ON CONFLICT (id) DO NOTHING;
