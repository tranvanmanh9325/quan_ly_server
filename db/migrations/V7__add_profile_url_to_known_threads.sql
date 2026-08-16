-- Migration: Add profile_url to facebook_known_threads for direct Facebook profile resolution
ALTER TABLE facebook_known_threads ADD COLUMN IF NOT EXISTS profile_url TEXT;
