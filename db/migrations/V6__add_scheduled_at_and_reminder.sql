-- ─── Add Scheduled Timestamp and Reminder Columns ───────────────────────────
-- Allows the system to automatically track appointment deadlines and dispatch
-- proactive reminders 1 hour (60 minutes) before the scheduled meeting time.

ALTER TABLE facebook_appointments
ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS reminder_sent BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_fb_appointments_reminder 
ON facebook_appointments(status, reminder_sent, scheduled_at);
