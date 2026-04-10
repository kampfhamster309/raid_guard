#!/usr/bin/env bash
# Integration tests for the EVE JSON ingestor.
# Spins up temporary TimescaleDB and Redis containers, applies the schema,
# then runs the pytest integration suite against them.
#
# Usage:
#   ./services/backend/tests/test_ingestor_integration.sh
# Run via: make test-ingestor (from the repo root)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "${SCRIPT_DIR}")"
REPO_ROOT="$(dirname "$(dirname "${SERVICE_DIR}")")"
SCHEMA_FILE="${REPO_ROOT}/services/db/init/01_schema.sql"

DB_CONTAINER="raid_guard_db_ingest_test_$$"
REDIS_CONTAINER="raid_guard_redis_ingest_test_$$"

DB_USER="testuser"
DB_PASSWORD="testpass"
DB_NAME="testdb"
DB_PORT="54321"      # non-standard to avoid conflicts
REDIS_PORT="63792"

DB_IMAGE="timescale/timescaledb:latest-pg16"
REDIS_IMAGE="redis:7-alpine"

cleanup() {
    docker rm -f "${DB_CONTAINER}"    > /dev/null 2>&1 || true
    docker rm -f "${REDIS_CONTAINER}" > /dev/null 2>&1 || true
}
trap cleanup EXIT

# ── Start containers ──────────────────────────────────────────────────────────

echo "==> Pulling images..."
docker pull "${DB_IMAGE}"    --quiet > /dev/null
docker pull "${REDIS_IMAGE}" --quiet > /dev/null

echo "==> Starting TimescaleDB container (${DB_CONTAINER})..."
docker run -d \
    --name "${DB_CONTAINER}" \
    -p "${DB_PORT}:5432" \
    -e POSTGRES_USER="${DB_USER}" \
    -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
    -e POSTGRES_DB="${DB_NAME}" \
    "${DB_IMAGE}" > /dev/null

echo "==> Starting Redis container (${REDIS_CONTAINER})..."
docker run -d \
    --name "${REDIS_CONTAINER}" \
    -p "${REDIS_PORT}:6379" \
    "${REDIS_IMAGE}" > /dev/null

# ── Wait for readiness ────────────────────────────────────────────────────────

wait_for_postgres() {
    local label="$1"
    echo "==> Waiting for Postgres (${label})..."
    for i in $(seq 1 45); do
        if docker exec "${DB_CONTAINER}" \
               pg_isready -U "${DB_USER}" -d "${DB_NAME}" > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
        if [ "${i}" -eq 45 ]; then
            echo "ERROR: Postgres did not become ready (${label})"
            exit 1
        fi
    done
}

wait_for_postgres "initial"
sleep 3   # TimescaleDB restarts Postgres once during init
wait_for_postgres "post-init"

echo "==> Waiting for Redis..."
for i in $(seq 1 20); do
    if docker exec "${REDIS_CONTAINER}" redis-cli ping > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
    if [ "${i}" -eq 20 ]; then
        echo "ERROR: Redis did not become ready within 10s"
        exit 1
    fi
done

# ── Apply schema ──────────────────────────────────────────────────────────────

echo "==> Applying database schema..."
docker exec -i "${DB_CONTAINER}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" < "${SCHEMA_FILE}" > /dev/null

# ── Run pytest ────────────────────────────────────────────────────────────────

echo "==> Running ingestor integration tests..."
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:${DB_PORT}/${DB_NAME}" \
REDIS_URL="redis://localhost:${REDIS_PORT}" \
    "${SERVICE_DIR}/.venv/bin/python" -m pytest \
        "${SCRIPT_DIR}/test_ingestor_integration.py" \
        -v

echo ""
echo "✓ All ingestor integration tests passed."
