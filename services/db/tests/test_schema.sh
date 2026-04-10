#!/usr/bin/env bash
# Integration tests for the TimescaleDB schema.
# Spins up a temporary TimescaleDB container, applies the schema, and validates
# tables, hypertables, policies, and basic CRUD.
#
# Usage:
#   ./services/db/tests/test_schema.sh
# Run via: make test-db (from the repo root)
set -euo pipefail

PASS=0
FAIL=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INIT_DIR="$(dirname "${SCRIPT_DIR}")/init"
SCHEMA_FILE="${INIT_DIR}/01_schema.sql"

CONTAINER="raid_guard_db_test_$$"
DB_USER="testuser"
DB_PASSWORD="testpass"
DB_NAME="testdb"
IMAGE="timescale/timescaledb:latest-pg16"

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

# Run a SQL query against the test container; returns stdout.
psql_exec() {
    docker exec "${CONTAINER}" \
        psql -U "${DB_USER}" -d "${DB_NAME}" -tAq -c "$1" 2>/dev/null
}

cleanup() {
    docker rm -f "${CONTAINER}" > /dev/null 2>&1 || true
}
trap cleanup EXIT

echo ""
echo "==> Pulling ${IMAGE}..."
docker pull "${IMAGE}" --quiet > /dev/null

echo "==> Starting temporary TimescaleDB container (${CONTAINER})..."
docker run -d \
    --name "${CONTAINER}" \
    -e POSTGRES_USER="${DB_USER}" \
    -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
    -e POSTGRES_DB="${DB_NAME}" \
    "${IMAGE}" > /dev/null

# Wait until Postgres is ready.
# TimescaleDB restarts Postgres once after first initialization, so we wait
# for two consecutive successful pg_isready checks separated by a brief pause.
wait_for_postgres() {
    local label="$1"
    echo "==> Waiting for Postgres to be ready (${label})..."
    for i in $(seq 1 45); do
        if docker exec "${CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
        if [ "${i}" -eq 45 ]; then
            echo "ERROR: Postgres did not become ready within 45s (${label})"
            exit 1
        fi
    done
}

wait_for_postgres "initial"
# Brief pause to let TimescaleDB finish its internal restart cycle
sleep 3
wait_for_postgres "post-init"

echo "==> Applying schema..."
docker exec -i "${CONTAINER}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" < "${SCHEMA_FILE}" > /dev/null

echo ""
echo "Testing schema..."
echo ""

# ── Test 1: tables exist ──────────────────────────────────────────────────────
for table in alerts incidents digests config; do
    result=$(psql_exec "SELECT COUNT(*) FROM information_schema.tables
                        WHERE table_schema='public' AND table_name='${table}';")
    [ "${result}" = "1" ] \
        && pass "table '${table}' exists" \
        || fail "table '${table}' exists"
done

# ── Test 2: hypertables registered ───────────────────────────────────────────
for ht in alerts incidents digests; do
    result=$(psql_exec "SELECT COUNT(*) FROM timescaledb_information.hypertables
                        WHERE hypertable_name='${ht}';")
    [ "${result}" = "1" ] \
        && pass "hypertable '${ht}' registered" \
        || fail "hypertable '${ht}' registered"
done

# config must NOT be a hypertable
result=$(psql_exec "SELECT COUNT(*) FROM timescaledb_information.hypertables
                    WHERE hypertable_name='config';")
[ "${result}" = "0" ] \
    && pass "config is a plain table (not a hypertable)" \
    || fail "config is a plain table (not a hypertable)"

# ── Test 3: severity_level enum ───────────────────────────────────────────────
result=$(psql_exec "SELECT COUNT(*) FROM pg_type WHERE typname='severity_level';")
[ "${result}" = "1" ] \
    && pass "severity_level enum type exists" \
    || fail "severity_level enum type exists"

# ── Test 4: compression policy on alerts ─────────────────────────────────────
result=$(psql_exec "SELECT COUNT(*) FROM timescaledb_information.jobs
                    WHERE hypertable_name='alerts'
                    AND proc_name='policy_compression';")
[ "${result}" = "1" ] \
    && pass "compression policy exists on alerts" \
    || fail "compression policy exists on alerts"

# ── Test 5: retention policies ───────────────────────────────────────────────
for ht in alerts incidents digests; do
    result=$(psql_exec "SELECT COUNT(*) FROM timescaledb_information.jobs
                        WHERE hypertable_name='${ht}'
                        AND proc_name='policy_retention';")
    [ "${result}" = "1" ] \
        && pass "retention policy exists on '${ht}'" \
        || fail "retention policy exists on '${ht}'"
done

# ── Test 6: default config values seeded ─────────────────────────────────────
result=$(psql_exec "SELECT value FROM config WHERE key='notification_min_severity';")
[ "${result}" = "warning" ] \
    && pass "config seed: notification_min_severity=warning" \
    || fail "config seed: notification_min_severity=warning (got '${result}')"

result=$(psql_exec "SELECT value FROM config WHERE key='ai_enrichment_enabled';")
[ "${result}" = "true" ] \
    && pass "config seed: ai_enrichment_enabled=true" \
    || fail "config seed: ai_enrichment_enabled=true (got '${result}')"

result=$(psql_exec "SELECT COUNT(*) FROM config;")
[ "${result}" = "6" ] \
    && pass "config seeded with 6 default rows" \
    || fail "config seeded with 6 default rows (got ${result})"

# ── Test 7: alert CRUD ────────────────────────────────────────────────────────
psql_exec "INSERT INTO alerts (timestamp, src_ip, dst_ip, src_port, dst_port,
                               proto, signature, signature_id, category,
                               severity, raw_json)
           VALUES (NOW(), '192.168.1.10', '1.2.3.4', 12345, 443,
                   'TCP', 'ET MALWARE Test', 9999999, 'Malware',
                   'critical', '{\"event_type\":\"alert\"}'::jsonb);" > /dev/null

result=$(psql_exec "SELECT COUNT(*) FROM alerts WHERE signature_id=9999999;")
[ "${result}" = "1" ] \
    && pass "alerts: insert and query by signature_id" \
    || fail "alerts: insert and query by signature_id"

# ── Test 8: incident CRUD ────────────────────────────────────────────────────
psql_exec "INSERT INTO incidents (period_start, period_end, risk_level)
           VALUES (NOW() - INTERVAL '1 hour', NOW(), 'high');" > /dev/null

result=$(psql_exec "SELECT COUNT(*) FROM incidents WHERE risk_level='high';")
[ "${result}" = "1" ] \
    && pass "incidents: insert and query by risk_level" \
    || fail "incidents: insert and query by risk_level"

# ── Test 9: digest CRUD ──────────────────────────────────────────────────────
psql_exec "INSERT INTO digests (period_start, period_end, content)
           VALUES (NOW() - INTERVAL '24 hours', NOW(), 'Test digest content');" > /dev/null

result=$(psql_exec "SELECT content FROM digests LIMIT 1;")
[ "${result}" = "Test digest content" ] \
    && pass "digests: insert and retrieve content" \
    || fail "digests: insert and retrieve content"

# ── Test 10: config upsert idempotency ───────────────────────────────────────
psql_exec "INSERT INTO config (key, value) VALUES ('notification_min_severity', 'critical')
           ON CONFLICT (key) DO NOTHING;" > /dev/null

result=$(psql_exec "SELECT value FROM config WHERE key='notification_min_severity';")
[ "${result}" = "warning" ] \
    && pass "config: ON CONFLICT DO NOTHING preserves existing value" \
    || fail "config: ON CONFLICT DO NOTHING preserves existing value (got '${result}')"

# ── Test 11: alerts indexes exist ────────────────────────────────────────────
for idx in alerts_src_ip_idx alerts_dst_ip_idx alerts_severity_idx alerts_signature_id_idx; do
    result=$(psql_exec "SELECT COUNT(*) FROM pg_indexes
                        WHERE tablename='alerts' AND indexname='${idx}';")
    [ "${result}" = "1" ] \
        && pass "index '${idx}' exists" \
        || fail "index '${idx}' exists"
done

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed."
[ "${FAIL}" -eq 0 ]
