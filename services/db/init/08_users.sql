-- Users table for RAID-020 multi-user auth.
-- Roles: 'admin' (full write access) or 'viewer' (read-only).
-- The application seeds the first admin from ADMIN_USERNAME/ADMIN_PASSWORD env
-- vars on startup if this table is empty.

CREATE TABLE IF NOT EXISTS users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    username      TEXT        NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    role          TEXT        NOT NULL DEFAULT 'viewer'
                  CHECK (role IN ('admin', 'viewer'))
);
