# raid_guard

> **Work in progress.** Core capture, detection, ingestion, and API layers are
> functional (RAID-001 through RAID-006). The React frontend, AI enrichment,
> alerting integrations, and active-response features are still under
> development. See `development_plan.md` for the full roadmap.

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
Unraid box. Active blocking is via Pi-hole v6 DNS sinkholing and a future
Fritzbox TR-064 investigation.

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
| Frontend (nginx placeholder) | http://localhost:3000 |

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
| `GET` | `/api/stats` | Last-24 h totals, hourly chart data, top source IPs, top signatures |
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
| `redis` | ✅ | Pub/sub event bus (`alerts:raw`, `alerts:enriched`) |
| `backend` | ✅ | FastAPI: REST API, WebSocket, EVE JSON ingestor background task |
| `frontend` | 🚧 | nginx placeholder — React PWA dashboard (RAID-007) |

---

## Running tests

```bash
# Backend unit tests (no external deps)
cd services/backend && .venv/bin/python -m pytest tests/test_health.py tests/test_ingestor.py tests/test_auth.py tests/test_alerts_api.py tests/test_stats_api.py tests/test_websocket.py -v

# Capture-agent unit tests
cd services/capture-agent && .venv/bin/python -m pytest tests/ -v

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
| `FRITZ_IFACE_ID` | `3-19` | Capture interface — try `3-0` if no traffic |
| `DB_USER` / `DB_NAME` | `raidguard` | TimescaleDB database name and user |
| `DB_PASSWORD` | — | TimescaleDB password |
| `REDIS_URL` | `redis://redis:6379` | Redis connection URL |
| `EVE_JSON_PATH` | `/var/log/suricata/eve.json` | Suricata EVE JSON log path |
| `ADMIN_USERNAME` | `admin` | Dashboard login username |
| `ADMIN_PASSWORD` | — | Dashboard login password (empty = login disabled) |
| `JWT_SECRET` | random | HS256 signing key — generate with `secrets.token_hex(32)` |
| `JWT_EXPIRY_HOURS` | `24` | Token lifetime |
| `LM_STUDIO_URL` | — | LM Studio base URL (e.g. `http://192.168.1.x:1234/v1`) |
| `LM_STUDIO_MODEL` | — | Model identifier (e.g. `gemma-4-27b`) |
| `PIHOLE_HOST` / `PIHOLE_PASSWORD` | — | Pi-hole v6 address and API password |
| `HA_WEBHOOK_URL` | — | Home Assistant webhook URL |

---

## License

Copyright 2026 Felix Harenbrock. Licensed under the [Apache License, Version 2.0](LICENSE).
