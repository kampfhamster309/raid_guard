#!/usr/bin/env bash
# Unit tests for entrypoint.sh logic.
# Uses mock binaries on PATH to avoid needing a real Suricata installation.
set -euo pipefail

PASS=0
FAIL=0
ENTRYPOINT="$(cd "$(dirname "$0")/.." && pwd)/entrypoint.sh"

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

echo ""
echo "Testing entrypoint.sh..."
echo ""

# ── Helper ────────────────────────────────────────────────────────────────────

# Run the entrypoint with mock binaries injected at the front of PATH.
# Args: <fifo_path> <update_exit_code> <args_out_file>
# Any extra env vars set by the caller are inherited.
run_entrypoint() {
    local fifo="$1"
    local update_exit="${2:-0}"
    local args_file="${3:-/dev/null}"
    local mock_dir
    mock_dir=$(mktemp -d)

    # Mock suricata-update: exits with the requested code
    cat > "${mock_dir}/suricata-update" << EOF
#!/bin/bash
exit ${update_exit}
EOF

    # Mock suricata: writes received args to file and exits cleanly
    cat > "${mock_dir}/suricata" << EOF
#!/bin/bash
echo "\$*" > '${args_file}'
exit 0
EOF

    chmod +x "${mock_dir}/suricata-update" "${mock_dir}/suricata"

    # Run the entrypoint; replace `exec suricata` so our mock is not exec'd
    # away (which would skip writing the args file).
    FIFO_PATH="${fifo}" PATH="${mock_dir}:${PATH}" \
        bash <(sed 's/^exec suricata\b/suricata/' "${ENTRYPOINT}") 2>/dev/null

    rm -rf "${mock_dir}"
}

# ── Test 1: proceeds immediately when FIFO exists ─────────────────────────────
TMP=$(mktemp -d)
FIFO="${TMP}/fritz.pcap"; mkfifo "${FIFO}"
ARGS="${TMP}/args"

run_entrypoint "${FIFO}" 0 "${ARGS}"
[ -f "${ARGS}" ] && pass "proceeds immediately when FIFO exists" \
                 || fail "proceeds immediately when FIFO exists"
rm -rf "${TMP}"

# ── Test 2: passes -r <fifo> to suricata; does NOT pass --pcap-file-continuous ──
# --pcap-file-continuous opens FIFOs with O_NONBLOCK, causing pcap_next_ex() to
# return -1 immediately when no packet is buffered yet.  We rely on blocking
# reads instead so Suricata waits for the first packet naturally.
TMP=$(mktemp -d)
FIFO="${TMP}/fritz.pcap"; mkfifo "${FIFO}"
ARGS="${TMP}/args"

run_entrypoint "${FIFO}" 0 "${ARGS}"
if [ -f "${ARGS}" ]; then
    SURICATA_ARGS=$(cat "${ARGS}")
    if echo "${SURICATA_ARGS}" | grep -q -- "-r ${FIFO}" \
    && ! echo "${SURICATA_ARGS}" | grep -q -- "--pcap-file-continuous"; then
        pass "passes -r <fifo> without --pcap-file-continuous"
    else
        fail "passes -r <fifo> without --pcap-file-continuous"
        echo "    Got: ${SURICATA_ARGS}"
    fi
else
    fail "passes -r <fifo> without --pcap-file-continuous (suricata not called)"
fi
rm -rf "${TMP}"

# ── Test 3: suricata-update failure does not abort startup ────────────────────
TMP=$(mktemp -d)
FIFO="${TMP}/fritz.pcap"; mkfifo "${FIFO}"
ARGS="${TMP}/args"

run_entrypoint "${FIFO}" 1 "${ARGS}"
[ -f "${ARGS}" ] && pass "suricata-update failure does not abort startup" \
                 || fail "suricata-update failure does not abort startup"
rm -rf "${TMP}"

# ── Test 4: respects SURICATA_LOG_DIR environment variable ────────────────────
TMP=$(mktemp -d)
FIFO="${TMP}/fritz.pcap"; mkfifo "${FIFO}"
ARGS="${TMP}/args"
LOG_DIR="${TMP}/logs"

SURICATA_LOG_DIR="${LOG_DIR}" run_entrypoint "${FIFO}" 0 "${ARGS}"
if [ -f "${ARGS}" ]; then
    SURICATA_ARGS=$(cat "${ARGS}")
    if echo "${SURICATA_ARGS}" | grep -q -- "-l ${LOG_DIR}"; then
        pass "respects SURICATA_LOG_DIR environment variable"
    else
        fail "respects SURICATA_LOG_DIR environment variable"
        echo "    Got: ${SURICATA_ARGS}"
    fi
else
    fail "respects SURICATA_LOG_DIR environment variable (suricata not called)"
fi
rm -rf "${TMP}"

# ── Test 5: passes -c <config> to suricata ────────────────────────────────────
TMP=$(mktemp -d)
FIFO="${TMP}/fritz.pcap"; mkfifo "${FIFO}"
ARGS="${TMP}/args"
CFG="${TMP}/custom.yaml"

SURICATA_CONFIG="${CFG}" run_entrypoint "${FIFO}" 0 "${ARGS}"
if [ -f "${ARGS}" ]; then
    SURICATA_ARGS=$(cat "${ARGS}")
    if echo "${SURICATA_ARGS}" | grep -q -- "-c ${CFG}"; then
        pass "passes -c <config> to suricata"
    else
        fail "passes -c <config> to suricata"
        echo "    Got: ${SURICATA_ARGS}"
    fi
else
    fail "passes -c <config> to suricata (suricata not called)"
fi
rm -rf "${TMP}"

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed."
[ "${FAIL}" -eq 0 ]
