-- RAID-015: batch correlation additions
-- Safe to run multiple times (IF NOT EXISTS / ON CONFLICT).
--
-- For fresh installs this runs automatically alongside 01_schema.sql.
-- For existing deployments run manually:
--   docker compose exec db psql -U raidguard raidguard \
--     -f /docker-entrypoint-initdb.d/02_correlation_config.sql

-- Add a human-readable name to incidents (was missing from initial schema).
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS name TEXT;

-- Correlation tuning parameters (read by the correlator at runtime).
INSERT INTO config (key, value) VALUES
    ('correlation_window_minutes', '30'),
    ('correlation_min_alerts',     '2')
ON CONFLICT (key) DO NOTHING;
