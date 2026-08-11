-- ─── Alter facebook_config text columns ──────────────────────────────────────────
-- Fix error: value too long for type character varying(255) when saving large cookies JSON.
ALTER TABLE facebook_config ALTER COLUMN cookies_json TYPE TEXT;
ALTER TABLE facebook_config ALTER COLUMN custom_message TYPE TEXT;
