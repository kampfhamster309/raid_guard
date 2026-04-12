-- RAID-015b: False positive / noise tuning suggestions
-- Stores LLM-generated recommendations for noisy Suricata signatures.

CREATE TABLE IF NOT EXISTS tuning_suggestions (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signature     TEXT        NOT NULL,
    signature_id  INT,
    hit_count     INT         NOT NULL,
    assessment    TEXT        NOT NULL,
    action        TEXT        NOT NULL CHECK (action IN ('suppress', 'threshold-adjust', 'keep')),
    status        TEXT        NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'confirmed', 'dismissed')),
    confirmed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS tuning_suggestions_status_idx
    ON tuning_suggestions (status, created_at DESC);

-- Configurable tuner parameters (all overridable from the UI once RAID-019 lands).
INSERT INTO config (key, value) VALUES
    ('tuner_lookback_days',  '7'),
    ('tuner_min_days',       '7'),
    ('tuner_interval_days',  '7'),
    ('tuner_min_alerts',     '10'),
    ('tuner_top_n',          '10')
ON CONFLICT (key) DO NOTHING;
