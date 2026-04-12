-- RAID-016: Pi-hole v6 DNS sinkhole integration settings.
-- No new table needed — all state lives in the Pi-hole instance itself.

INSERT INTO config (key, value) VALUES
    ('pihole_url',      ''),
    ('pihole_password', ''),
    ('pihole_enabled',  'false')
ON CONFLICT (key) DO NOTHING;
