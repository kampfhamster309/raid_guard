-- raid_guard database schema
-- TimescaleDB hypertables with retention and compression policies.
-- Executed automatically by the postgres container on first start
-- (via /docker-entrypoint-initdb.d).

-- ── Extensions ───────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ── Types ────────────────────────────────────────────────────────────────────

CREATE TYPE severity_level AS ENUM ('info', 'warning', 'critical');

-- ── alerts ───────────────────────────────────────────────────────────────────
-- One row per Suricata alert event.  Partitioned by timestamp (hypertable).

CREATE TABLE IF NOT EXISTS alerts (
    id              UUID            NOT NULL DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ     NOT NULL,
    src_ip          INET,
    dst_ip          INET,
    src_port        INTEGER,
    dst_port        INTEGER,
    proto           TEXT,
    signature       TEXT,
    signature_id    INTEGER,
    category        TEXT,
    severity        severity_level  NOT NULL DEFAULT 'info',
    raw_json        JSONB           NOT NULL,
    enrichment_json JSONB,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

SELECT create_hypertable(
    'alerts',
    'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- Secondary indexes for common query patterns
CREATE INDEX IF NOT EXISTS alerts_src_ip_idx        ON alerts (src_ip,        timestamp DESC);
CREATE INDEX IF NOT EXISTS alerts_dst_ip_idx        ON alerts (dst_ip,        timestamp DESC);
CREATE INDEX IF NOT EXISTS alerts_severity_idx      ON alerts (severity,      timestamp DESC);
CREATE INDEX IF NOT EXISTS alerts_signature_id_idx  ON alerts (signature_id,  timestamp DESC);

-- Compress chunks older than 7 days (orderby timestamp for best ratio)
ALTER TABLE alerts SET (
    timescaledb.compress,
    timescaledb.compress_orderby      = 'timestamp DESC',
    timescaledb.compress_segmentby    = 'severity'
);

SELECT add_compression_policy(
    'alerts',
    compress_after  => INTERVAL '7 days',
    if_not_exists   => TRUE
);

-- Retain data for 90 days
SELECT add_retention_policy(
    'alerts',
    drop_after    => INTERVAL '90 days',
    if_not_exists => TRUE
);

-- ── incidents ─────────────────────────────────────────────────────────────────
-- AI-correlated incidents spanning multiple alerts.

CREATE TABLE IF NOT EXISTS incidents (
    id              UUID    NOT NULL DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    alert_ids       UUID[]  NOT NULL DEFAULT '{}',
    narrative       TEXT,
    risk_level      TEXT    NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    PRIMARY KEY (id, created_at)
);

SELECT create_hypertable(
    'incidents',
    'created_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE
);

-- Retain incidents for 1 year
SELECT add_retention_policy(
    'incidents',
    drop_after    => INTERVAL '365 days',
    if_not_exists => TRUE
);

-- ── digests ───────────────────────────────────────────────────────────────────
-- Periodic AI-generated digest summaries.

CREATE TABLE IF NOT EXISTS digests (
    id              UUID        NOT NULL DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    content         TEXT        NOT NULL,
    PRIMARY KEY (id, created_at)
);

SELECT create_hypertable(
    'digests',
    'created_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists       => TRUE
);

-- Retain digests for 1 year
SELECT add_retention_policy(
    'digests',
    drop_after    => INTERVAL '365 days',
    if_not_exists => TRUE
);

-- ── config ────────────────────────────────────────────────────────────────────
-- Key-value configuration store (non-time-series; plain table).

CREATE TABLE IF NOT EXISTS config (
    key         TEXT        PRIMARY KEY,
    value       TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Default configuration seed
INSERT INTO config (key, value) VALUES
    ('notification_min_severity',   'warning'),
    ('ai_enrichment_enabled',       'true'),
    ('ai_batch_interval_seconds',   '300'),
    ('retention_alerts_days',       '90'),
    ('retention_incidents_days',    '365'),
    ('retention_digests_days',      '365')
ON CONFLICT (key) DO NOTHING;
