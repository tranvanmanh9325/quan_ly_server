-- Migration: Add disk_percent column to server_metrics table
-- Apply this script on the production database BEFORE deploying the new backend version.
--
-- Backup first:
--   pg_dump -U dashboard_user quan_ly_server > backup_$(date +%Y%m%d_%H%M%S).sql
--
-- Run:
--   psql -U dashboard_user -d quan_ly_server -f V2__add_disk_percent.sql

ALTER TABLE server_metrics
    ADD COLUMN IF NOT EXISTS disk_percent DOUBLE PRECISION;
