-- ==============================================================================
-- Migration V19: Autonomous Goal Engine Tasks Table (R1)
-- Persistence for Multi-Step Autonomous Goals & Sub-task Execution
-- ==============================================================================

CREATE TABLE IF NOT EXISTS agent_tasks (
    id                  VARCHAR(64) PRIMARY KEY,
    goal                TEXT NOT NULL,
    steps               JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_step        INT NOT NULL DEFAULT 0,
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    trigger_condition   TEXT,
    chat_id             VARCHAR(64),
    result_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    retry_count         INT NOT NULL DEFAULT 0,
    max_retries         INT NOT NULL DEFAULT 3,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMPTZ
);

-- Index for querying task lifecycle status
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status 
    ON agent_tasks (status);

-- Composite index for 30s background polling loop
CREATE INDEX IF NOT EXISTS idx_agent_tasks_active_poll 
    ON agent_tasks (status, created_at ASC);
