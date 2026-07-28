-- Migration: Initial schema for server_metrics table
-- Apply this script first to create the base table before running V2.

CREATE TABLE IF NOT EXISTS server_metrics (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    cpu_percent DOUBLE PRECISION,
    ram_percent DOUBLE PRECISION
);
