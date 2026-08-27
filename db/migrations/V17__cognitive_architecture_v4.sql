-- V17: Cognitive Architecture v4.0 -- STDP Causal Chains + Schema Memory Engine

-- P6: STDP Causal Chains
CREATE TABLE IF NOT EXISTS agent_causal_chains (
    id             SERIAL PRIMARY KEY,
    tool_a         VARCHAR(100) NOT NULL,
    tool_b         VARCHAR(100) NOT NULL,
    success_count  INT NOT NULL DEFAULT 0,
    fail_count     INT NOT NULL DEFAULT 0,
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tool_a, tool_b)
);
CREATE INDEX IF NOT EXISTS idx_causal_tool_a ON agent_causal_chains(tool_a);

-- P10: Schema Memory Engine
CREATE TABLE IF NOT EXISTS agent_schemas (
    id               SERIAL PRIMARY KEY,
    schema_name      VARCHAR(200) NOT NULL UNIQUE,
    pattern_text     TEXT NOT NULL,
    occurrence_count INT NOT NULL DEFAULT 1,
    confidence       DECIMAL(4,3) NOT NULL DEFAULT 0.700,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_schemas_active ON agent_schemas(is_active, occurrence_count DESC);
