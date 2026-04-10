#!/usr/bin/env bash
# Integration tests for Redis pub/sub channel definitions.
# Spins up a temporary Redis container, runs the pytest suite against it,
# then tears the container down.
#
# Usage:
#   ./services/backend/tests/test_channels.sh
# Run via: make test-redis (from the repo root)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "${SCRIPT_DIR}")"

CONTAINER="raid_guard_redis_test_$$"
REDIS_PORT="63791"  # non-standard port to avoid conflicts with a running Redis
IMAGE="redis:7-alpine"

cleanup() {
    docker rm -f "${CONTAINER}" > /dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Pulling ${IMAGE}..."
docker pull "${IMAGE}" --quiet > /dev/null

echo "==> Starting temporary Redis container (${CONTAINER})..."
docker run -d \
    --name "${CONTAINER}" \
    -p "${REDIS_PORT}:6379" \
    "${IMAGE}" > /dev/null

echo "==> Waiting for Redis to be ready..."
for i in $(seq 1 20); do
    if docker exec "${CONTAINER}" redis-cli ping > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
    if [ "${i}" -eq 20 ]; then
        echo "ERROR: Redis did not become ready within 10s"
        exit 1
    fi
done

echo "==> Running Redis pub/sub integration tests..."
REDIS_URL="redis://localhost:${REDIS_PORT}" \
    "${SERVICE_DIR}/.venv/bin/python" -m pytest \
        "${SCRIPT_DIR}/test_channels.py" \
        -v

echo ""
echo "✓ All Redis pub/sub tests passed."
