#!/usr/bin/env bash
# Validates the Suricata configuration by running `suricata -T` inside the
# built Docker image.  Requires Docker and a built image.
#
# Usage:
#   ./tests/test_config.sh [image-tag]
#
# The image-tag defaults to raid_guard/suricata:test.
# Run via: make test-suricata (from the repo root)
set -euo pipefail

IMAGE="${1:-raid_guard/suricata:test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "${SCRIPT_DIR}")"

echo "==> Building ${IMAGE}..."
docker build -t "${IMAGE}" "${SERVICE_DIR}" --quiet

echo "==> Validating suricata.yaml with 'suricata -T'..."
# Use --entrypoint to bypass our startup script and invoke suricata directly.
docker run --rm --entrypoint suricata "${IMAGE}" \
    -T -c /etc/suricata/suricata.yaml -v 2>&1

echo "✓ Suricata configuration is valid."

echo "==> Cleaning up test image..."
docker rmi "${IMAGE}" --force > /dev/null

echo "✓ All Suricata tests passed."
