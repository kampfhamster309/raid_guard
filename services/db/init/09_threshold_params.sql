-- Migration: add LLM-suggested threshold parameters to tuning_suggestions.
-- Safe to re-run (ADD COLUMN IF NOT EXISTS).
-- For existing deployments run manually:
--   docker compose exec db psql -U raidguard raidguard \
--     -f /docker-entrypoint-initdb.d/09_threshold_params.sql

ALTER TABLE tuning_suggestions
    ADD COLUMN IF NOT EXISTS threshold_count   INTEGER,
    ADD COLUMN IF NOT EXISTS threshold_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS threshold_track   TEXT CHECK (threshold_track IN ('by_src', 'by_dst')),
    ADD COLUMN IF NOT EXISTS threshold_type    TEXT CHECK (threshold_type IN ('limit', 'threshold', 'both'));
