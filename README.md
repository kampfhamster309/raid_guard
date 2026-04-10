# raid_guard

Network intrusion detection system for Unraid, powered by Suricata and an on-premises LLM.

## Architecture overview

```
Fritzbox → capture-agent → FIFO → Suricata → ingestor → TimescaleDB / Redis → backend → frontend
                                                                                       ↓
                                                                               Pi-hole (sinkhole)
                                                                               Home Assistant (alerts)
```

## Prerequisites

- Docker and Docker Compose on the dev machine
- Access to the Unraid server's Docker registry (`<unraid-host>:5000`)
- `UNRAID_HOST` env var set for push/deploy operations

## Setup

```bash
cp .env.example .env
# Edit .env and fill in all values
```

## Build & deploy

```bash
# Build all service images locally
make build

# Build and push to the Unraid registry (requires UNRAID_HOST)
make build-push

# Pull latest images on Unraid and restart services
make deploy
```

## Running locally

```bash
docker compose up
```

Services:
| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| Backend health | http://localhost:8000/health |
| Frontend | http://localhost:3000 |

## Services

| Service | Description |
|---------|-------------|
| `capture-agent` | Authenticates with the Fritzbox and streams PCAP to a shared FIFO (RAID-002) |
| `suricata` | Reads PCAP from the FIFO, produces EVE JSON alerts (RAID-002b) |
| `backend` | FastAPI REST API, WebSocket push, alert ingestor, AI enricher |
| `frontend` | React PWA dashboard (RAID-007) |
| `db` | TimescaleDB for time-series alert storage |
| `redis` | Pub/sub event bus for real-time alert streaming |
