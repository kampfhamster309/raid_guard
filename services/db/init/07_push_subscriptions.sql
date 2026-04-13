-- Web Push subscriptions table (RAID-019).
-- Stores browser push subscription endpoints and ECDH keys.
-- Each endpoint is unique; re-subscribing with the same endpoint upserts the keys.

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    endpoint   TEXT        NOT NULL UNIQUE,
    p256dh     TEXT        NOT NULL,
    auth       TEXT        NOT NULL
);
