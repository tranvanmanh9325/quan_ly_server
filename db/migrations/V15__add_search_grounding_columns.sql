-- V15: Add search_query and search_results columns to agent_memories
-- Enables storing the Google/DuckDuckGo search context used during
-- search-grounded lesson extraction (Search → Reflect → Save loop).

ALTER TABLE agent_memories
    ADD COLUMN IF NOT EXISTS search_query   TEXT,
    ADD COLUMN IF NOT EXISTS search_results TEXT;

-- Also add a grounded flag to agent_lessons to track which lessons
-- are backed by web search evidence vs purely LLM introspection.
ALTER TABLE agent_lessons
    ADD COLUMN IF NOT EXISTS is_search_grounded BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS search_query        TEXT;
