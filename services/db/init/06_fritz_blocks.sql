-- RAID-018: Fritzbox TR-064 device quarantine tracking
--
-- Blocked devices are recorded here so the UI can list them without making
-- N+1 calls to the Fritzbox.  The Fritzbox is authoritative; this table
-- mirrors what we sent — it may drift if an admin manually unblocks a device
-- via the Fritzbox UI.

CREATE TABLE IF NOT EXISTS fritz_blocked_devices (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    blocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip         TEXT        NOT NULL UNIQUE,
    hostname   TEXT,
    comment    TEXT
);
