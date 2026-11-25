#!/usr/bin/env bash
# raid_guard — Suricata entrypoint
# 1. Update ET Open rules (cached; skips download if fresh)
# 2. Wait for the capture-agent FIFO
# 3. Keep eve.json below EVE_JSON_MAX_BYTES (background check, hourly)
# 4. Start Suricata in PCAP-file-continuous mode
set -euo pipefail

FIFO_PATH="${FIFO_PATH:-/pcap/fritz.pcap}"
SURICATA_LOG_DIR="${SURICATA_LOG_DIR:-/var/log/suricata}"
SURICATA_CONFIG="${SURICATA_CONFIG:-/etc/suricata/suricata.yaml}"

# ── 1. Update rules ───────────────────────────────────────────────────────────
echo "[entrypoint] Updating Suricata rules (ET Open)..."
DISABLE_CONF="${SURICATA_DISABLE_CONF:-/etc/suricata/custom/disable.conf}"
if [ -f "${DISABLE_CONF}" ]; then
    echo "[entrypoint] Applying disable.conf: ${DISABLE_CONF}"
    UPDATE_CMD="suricata-update --no-test --disable-conf ${DISABLE_CONF}"
else
    UPDATE_CMD="suricata-update --no-test"
fi
if ${UPDATE_CMD} 2>&1; then
    echo "[entrypoint] Rules updated successfully."
else
    echo "[entrypoint] WARNING: suricata-update failed. Using existing rules if available."
fi

# ── 2. Wait for FIFO ──────────────────────────────────────────────────────────
echo "[entrypoint] Waiting for FIFO at ${FIFO_PATH}..."
until [ -p "${FIFO_PATH}" ]; do
    sleep 2
done
echo "[entrypoint] FIFO found."

# ── 3. Cap eve.json size ──────────────────────────────────────────────────────
# rotate-interval only switches files when the filename has a date pattern, so
# a fixed eve.json just grows.  The backend ingestor follows a truncated file
# from the start.  shortcut: lines the ingestor hasn't read yet (backend down)
# are lost on truncate; raise EVE_JSON_MAX_BYTES if that matters.  0 disables.
EVE_JSON_MAX_BYTES="${EVE_JSON_MAX_BYTES:-1073741824}"
if [ "${EVE_JSON_MAX_BYTES}" -gt 0 ]; then
    (
        while sleep 3600; do
            EVE="${SURICATA_LOG_DIR}/eve.json"
            if [ -f "${EVE}" ] && [ "$(stat -c %s "${EVE}")" -gt "${EVE_JSON_MAX_BYTES}" ]; then
                echo "[entrypoint] eve.json over ${EVE_JSON_MAX_BYTES} bytes — truncating"
                truncate -s 0 "${EVE}"
            fi
        done
    ) &
fi

# ── 4. Start Suricata ─────────────────────────────────────────────────────────
echo "[entrypoint] Starting Suricata..."
exec suricata \
    -c "${SURICATA_CONFIG}" \
    -r "${FIFO_PATH}" \
    -l "${SURICATA_LOG_DIR}"
