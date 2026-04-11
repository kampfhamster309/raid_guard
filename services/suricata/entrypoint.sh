#!/usr/bin/env bash
# raid_guard — Suricata entrypoint
# 1. Update ET Open rules (cached; skips download if fresh)
# 2. Wait for the capture-agent FIFO
# 3. Start Suricata in PCAP-file-continuous mode
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

# ── 3. Start Suricata ─────────────────────────────────────────────────────────
echo "[entrypoint] Starting Suricata..."
exec suricata \
    -c "${SURICATA_CONFIG}" \
    -r "${FIFO_PATH}" \
    -l "${SURICATA_LOG_DIR}"
