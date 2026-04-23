# raid_guard

> **Work in progress.** Capture, detection, ingestion, API, dashboard, rule
> configuration, Home Assistant push notifications, AI alert enrichment,
> AI batch incident correlation, periodic security digests, AI-driven noise
> tuning with live Suricata threshold application, Pi-hole DNS sinkholing,
> Fritzbox device quarantine, and PWA with Web Push notifications are
> functional (RAID-001 through RAID-021).
> See `development_plan.md` for the full roadmap.

Network intrusion detection system for Unraid, powered by Suricata and an
on-premises LLM. Traffic is captured from an AVM Fritzbox router, analysed
in real-time, and surfaced via a web dashboard with Home Assistant push
notifications.

---

## Architecture

```
Fritzbox → capture-agent → FIFO (/pcap/) → Suricata (IDS only)
                                                    ↓ EVE JSON
                                               ingestor (backend)
                                                    ↓
                                         TimescaleDB  +  Redis
                                                    ↓
                                           FastAPI backend
                                          ↙              ↘
                                  React frontend      Notification router
                                  (PWA, port 3000)         ↓
                                                    Home Assistant (push)
                                                    Pi-hole v6 (sinkhole)
```

Inline IPS is permanently out of scope — traffic does not pass through the
Unraid box. Active blocking uses two backends: Pi-hole v6 DNS sinkholing
(domain-based) and Fritzbox TR-064 device quarantine (LAN device WAN cutoff).

---

## Prerequisites

- Docker and Docker Compose on the dev machine
- Access to the Unraid server's Docker registry (`<unraid-host>:5000`)
- `UNRAID_HOST` env var set in your shell for push/deploy operations

---

## Setup

```bash
cp .env.example .env
# Edit .env — at minimum set:
#   FRITZ_USER / FRITZ_PASSWORD   (Fritzbox credentials)
#   DB_PASSWORD                   (TimescaleDB password)
#   ADMIN_PASSWORD                (dashboard login)
#   JWT_SECRET                    (see note below)
```

Generate a JWT secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

If `JWT_SECRET` is not set, a random value is used at startup and all
sessions are invalidated on every restart.

---

## Build & deploy

```bash
export UNRAID_HOST=192.168.1.x

make build        # build all service images locally
make push         # push to the Unraid registry
make build-push   # build + push in one step
make deploy       # pull latest on Unraid and restart all services
```

---

## Running locally

```bash
docker compose up
```

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| Backend health (no auth) | http://localhost:8000/health |
| Swagger UI | http://localhost:8000/docs |
| Frontend (React PWA) | http://localhost:3000 |

---

## Authentication

All `/api/*` endpoints require a Bearer token. Obtain one with:

```bash
curl -s -X POST http://localhost:8000/api/auth/token \
     -d "username=admin&password=<ADMIN_PASSWORD>"
```

Response:

```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```

Pass the token in subsequent requests:

```bash
curl -H "Authorization: Bearer <jwt>" http://localhost:8000/api/alerts
```

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/token` | Obtain a JWT (form: `username`, `password`) |
| `GET` | `/api/alerts` | Paginated alert list — query params: `limit`, `offset`, `severity`, `src_ip`, `after`, `before` |
| `GET` | `/api/alerts/{id}` | Single alert detail including raw EVE JSON |
| `POST` | `/api/alerts/{id}/enrich` | Trigger on-demand LLM enrichment for an alert (422 if LLM not configured, 504 on timeout) |
| `GET` | `/api/stats` | Last-24 h totals, per-severity hourly chart data (`info`/`warning`/`critical`), top source IPs, top signatures |
| `GET` | `/api/incidents` | Paginated incident list — query params: `limit` (default 20), `offset` |
| `GET` | `/api/incidents/{id}` | Single incident detail including the full list of related alerts |
| `GET` | `/api/digests` | Paginated digest list — query params: `limit` (default 10), `offset` |
| `GET` | `/api/digests/{id}` | Single digest with full JSON content |
| `POST` | `/api/digests/generate` | Trigger an immediate digest (200 with digest, 204 if too few alerts, 422 if LLM not configured) |
| `GET` | `/api/tuning` | List pending tuning suggestions (ordered by hit count) |
| `POST` | `/api/tuning/{id}/confirm` | Confirm suggestion — applies suppression or threshold directive to Suricata and reloads rules; accepts optional JSON body with threshold params (`threshold_count`, `threshold_seconds`, `threshold_track`, `threshold_type`) for threshold-adjust suggestions |
| `POST` | `/api/tuning/{id}/dismiss` | Dismiss suggestion without applying any change |
| `POST` | `/api/tuning/run` | Trigger immediate tuning analysis (200 with suggestions list, 422 if LLM not configured) |
| `GET` | `/api/rules/categories` | List ET Open rule categories with enabled/disabled state |
| `PUT` | `/api/rules/categories` | Update disabled categories (body: `{"disabled": ["emerging-p2p", ...]}`) |
| `POST` | `/api/rules/reload` | Run `suricata-update` + SIGHUP inside the Suricata container |
| `GET` | `/api/settings/push-threshold` | Get current notification push threshold (`info`/`warning`/`critical`) |
| `PUT` | `/api/settings/push-threshold` | Set push threshold (body: `{"threshold": "warning"}`) |
| `GET` | `/api/settings/ha` | Get HA integration state (`{"enabled": bool, "configured": bool}`) |
| `PUT` | `/api/settings/ha` | Enable or disable HA push notifications (body: `{"enabled": bool}`) |
| `POST` | `/api/settings/ha/test` | Send a synthetic test notification to the configured HA webhook |
| `GET` | `/api/settings/llm` | Get LM Studio configuration (URL, model, timeout, max tokens) |
| `PUT` | `/api/settings/llm` | Persist LM Studio configuration to the config table |
| `POST` | `/api/settings/llm/test` | Send a synthetic alert to the LLM and return the raw response |
| `GET` | `/api/pihole/settings` | Pi-hole connection settings (`{url, enabled, configured}` — password never returned) |
| `PUT` | `/api/pihole/settings` | Update Pi-hole URL / enabled flag / password (blank password = keep existing) |
| `GET` | `/api/pihole/blocklist` | List all exact deny-list domains from Pi-hole |
| `POST` | `/api/pihole/block` | Add a domain to Pi-hole's deny list (body: `{"domain": "..."}`) |
| `DELETE` | `/api/pihole/block/{domain}` | Remove a domain from Pi-hole's deny list |
| `GET` | `/api/fritz/status` | Fritzbox connectivity check and HostFilter service availability |
| `GET` | `/api/fritz/blocked` | List quarantined LAN devices (from DB) |
| `POST` | `/api/fritz/block` | Quarantine a LAN device — cuts off all WAN access (body: `{"ip": "..."}`) |
| `DELETE` | `/api/fritz/block/{ip}` | Lift quarantine for a device and restore WAN access |
| `GET` | `/api/push/vapid-public-key` | Return VAPID public key for browser push subscription |
| `POST` | `/api/push/subscribe` | Save a browser push subscription (body: `{"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}}`) |
| `DELETE` | `/api/push/subscribe` | Remove a push subscription (body: `{"endpoint": "..."}`) |
| `WS` | `/ws/alerts?token=<jwt>` | Live alert feed (subscribes to `alerts:enriched` Redis channel) |
| `GET` | `/health` | Liveness check (no auth) |

Full interactive docs at `/docs` (Swagger UI) and `/redoc`.

---

## Services

| Service | Status | Description |
|---------|--------|-------------|
| `capture-agent` | ✅ | Authenticates with Fritzbox, streams libpcap via HTTP to a shared FIFO |
| `suricata` | ✅ | Reads PCAP from FIFO, runs ET Open rules, outputs EVE JSON |
| `db` | ✅ | TimescaleDB — hypertable schema with 90-day retention and 7-day compression |
| `redis` | ✅ | Pub/sub event bus (`alerts:raw`, `alerts:enriched`, `incidents:new`, `digests:new`) |
| `backend` | ✅ | FastAPI: REST API, WebSocket, EVE JSON ingestor, AI enricher (bulk + on-demand), batch correlator, periodic digest worker, noise tuner with live Suricata threshold/suppress apply, rule management, notification router (HA push + Web Push), Pi-hole sinkhole client, Fritzbox TR-064 quarantine |
| `frontend` | ✅ | React PWA — live alert feed, on-demand AI re-analysis, per-severity stacked bar chart, incidents view, digests view, unified blocklist (Pi-hole + Fritzbox), rule config, LLM + HA + Web Push settings, tuning suggestions with inline threshold form |

---

## Running tests

```bash
# Backend unit tests (no external deps)
cd services/backend && .venv/bin/python -m pytest tests/ --ignore=tests/test_ingestor_integration.py -v

# Capture-agent unit tests
cd services/capture-agent && .venv/bin/python -m pytest tests/ -v

# Frontend unit tests (no external deps)
cd services/frontend && npm test

# Integration tests (each spins up real Docker containers, then tears them down)
make test-suricata   # Suricata config validation + entrypoint logic
make test-db         # TimescaleDB schema, hypertables, retention policies, CRUD
make test-redis      # Redis pub/sub channel definitions
make test-ingestor   # Full ingest_alert path against real DB + Redis
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `UNRAID_HOST` | — | Unraid server IP (shell env var for make push/deploy) |
| `FRITZ_HOST` | `192.168.178.1` | Fritzbox IP |
| `FRITZ_USER` / `FRITZ_PASSWORD` | — | Fritzbox credentials |
| `FRITZ_IFACE_ID` | `3-17` | Capture interface — find yours at `http://192.168.178.1/html/capture.html` |
| `DB_USER` / `DB_NAME` | `raidguard` | TimescaleDB database name and user |
| `DB_PASSWORD` | — | TimescaleDB password |
| `REDIS_URL` | `redis://redis:6379` | Redis connection URL |
| `EVE_JSON_PATH` | `/var/log/suricata/eve.json` | Suricata EVE JSON log path |
| `ADMIN_USERNAME` | `admin` | Dashboard login username |
| `ADMIN_PASSWORD` | — | Dashboard login password (empty = login disabled) |
| `JWT_SECRET` | random | HS256 signing key — generate with `secrets.token_hex(32)` |
| `JWT_EXPIRY_HOURS` | `24` | Token lifetime |
| `SURICATA_CONTAINER_NAME` | `suricata` | Docker container name for rule reload |
| `SURICATA_DISABLE_CONF` | `/suricata/config/disable.conf` | Path inside the backend container to the disable.conf written by rule management |
| `LM_STUDIO_URL` | — | LM Studio base URL (e.g. `http://192.168.1.x:1234/v1`) |
| `LM_STUDIO_MODEL` | — | Model identifier (e.g. `gemma-4-27b`) |
| `LM_ENRICHMENT_TIMEOUT` | `90` | LLM request timeout in seconds |
| `LM_MAX_TOKENS` | `512` | Maximum tokens in the LLM response |
| `PIHOLE_HOST` / `PIHOLE_PASSWORD` | — | Pi-hole v6 address and API password |
| `HA_WEBHOOK_URL` | — | Home Assistant webhook URL (leave unset to disable HA push) |
| `DASHBOARD_URL` | — | Public URL of the raid_guard dashboard — used to generate deep links in push notifications (e.g. `http://unraid:3000`) |
| `VAPID_PRIVATE_KEY` | — | VAPID private key (base64url) — generate with `py_vapid` (see `.env.example`) |
| `VAPID_PUBLIC_KEY` | — | VAPID public key (base64url) — served to browsers for push subscription |
| `VAPID_SUBJECT` | `mailto:admin@example.com` | VAPID subject — `mailto:` or `https:` URI identifying the push service contact |

---

## Home Assistant integration

raid_guard sends alert notifications to Home Assistant via a webhook. Each
notification includes enough context to drive rich HA automations, and a deep
link that opens the specific alert in the dashboard when the notification is
tapped in the Companion App.

### 1 — Create a webhook automation in HA

In Home Assistant, go to **Settings → Automations → Create automation → Start
from scratch**, then switch to YAML mode and paste:

```yaml
alias: raid_guard alert notification
description: Forward raid_guard IDS alerts to mobile devices
trigger:
  - platform: webhook
    webhook_id: raid_guard_alerts   # choose any unique ID
    allowed_methods:
      - POST
    local_only: true                # only accept from the local network
condition: []
action:
  - service: notify.mobile_app_your_phone   # replace with your device
    data:
      title: "{{ trigger.json.title }}"
      message: "{{ trigger.json.message }}"
      data:
        url: "{{ trigger.json.url }}"       # tap → opens alert in dashboard
        tag: "raid_guard_{{ trigger.json.alert_id }}"
        group: raid_guard
        color: >
          {% if trigger.json.severity == 'critical' %}red
          {% elif trigger.json.severity == 'warning' %}orange
          {% else %}blue{% endif %}
mode: queued
max: 20
```

After saving, copy the webhook URL from the automation's trigger card. It
looks like:

```
http://<ha-host>:8123/api/webhook/raid_guard_alerts
```

### 2 — Configure raid_guard

Set the following in your `.env`:

```bash
HA_WEBHOOK_URL=http://<ha-host>:8123/api/webhook/raid_guard_alerts
DASHBOARD_URL=http://<unraid-host>:3000
```

Rebuild and redeploy the backend, or just restart the backend container:

```bash
docker compose restart backend
```

### 3 — Set push threshold and verify

In the raid_guard dashboard, go to **Config → Notifications**:

- Use the toggle to enable or disable HA notifications at runtime (no restart needed).
- Use **Send test** to fire a synthetic notification to HA immediately and confirm delivery.

The push threshold (default: `warning`) controls the minimum severity that
triggers a push. `info` alerts are always stored and visible in the dashboard
but are not pushed unless you lower the threshold.

### Webhook payload reference

Every POST to your HA webhook contains these fields, accessible in automations
as `trigger.json.<field>`:

| Field | Example | Description |
|-------|---------|-------------|
| `title` | `raid_guard — WARNING` | Notification title |
| `message` | `Port scan detected from 192.168.1.5` | AI summary (if enriched) or signature + src IP |
| `severity` | `warning` | `info` / `warning` / `critical` |
| `signature` | `ET SCAN Potential SSH Scan` | Suricata rule name |
| `src_ip` | `192.168.1.5` | Source IP address |
| `timestamp` | `2026-04-11T14:32:00+00:00` | Alert timestamp (ISO 8601) |
| `alert_id` | `a1b2c3d4-…` | UUID of the alert record |
| `url` | `http://unraid:3000?alert=a1b2c3d4-…` | Deep link to the alert drawer (empty if `DASHBOARD_URL` not set) |

### Advanced: severity-based routing

You can split notifications by severity, for example to only wake you up for
`critical` alerts:

```yaml
alias: raid_guard — critical only
trigger:
  - platform: webhook
    webhook_id: raid_guard_alerts
    allowed_methods: [POST]
    local_only: true
condition:
  - condition: template
    value_template: "{{ trigger.json.severity == 'critical' }}"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "{{ trigger.json.title }}"
      message: "{{ trigger.json.message }}"
      data:
        url: "{{ trigger.json.url }}"
        push:
          sound: default
          interruption-level: critical  # iOS — bypasses silent mode
```

---

## License

Copyright 2026 Felix Harenbrock. Licensed under the [Apache License, Version 2.0](LICENSE).
