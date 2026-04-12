-- RAID-015a: digest configuration and schema additions
-- Safe to run multiple times (IF NOT EXISTS / ON CONFLICT).
--
-- For fresh installs this runs automatically alongside 01_schema.sql.
-- For existing deployments run manually:
--   docker compose exec db psql -U raidguard raidguard \
--     -f /docker-entrypoint-initdb.d/03_digest_config.sql

-- Add a risk-level summary to digests (avoids parsing JSON for the list view).
ALTER TABLE digests ADD COLUMN IF NOT EXISTS risk_level TEXT;

-- Digest scheduling and delivery parameters.
INSERT INTO config (key, value) VALUES
    ('digest_interval_hours', '24'),
    ('digest_min_alerts',     '5'),
    ('digest_notify_ha',      'false')
ON CONFLICT (key) DO NOTHING;
