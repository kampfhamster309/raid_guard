"""
Suricata rule category management.

Reads/writes the ``disabled_rule_categories`` config key in TimescaleDB and
manages the disable.conf file consumed by suricata-update.  Live reloads are
triggered by exec-ing suricata-update inside the Suricata container via the
Docker API, then sending SIGHUP so Suricata reloads rules without restarting.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

# ── Paths & container config ──────────────────────────────────────────────────

# Path to the disable.conf *inside the backend container* (suricata_config vol).
DISABLE_CONF_PATH = Path(
    os.environ.get("SURICATA_DISABLE_CONF", "/suricata/config/disable.conf")
)

# Path to the suppress.conf used by Suricata's threshold engine.
SUPPRESS_CONF_PATH = Path(
    os.environ.get("SURICATA_SUPPRESS_CONF", "/suricata/config/suppress.conf")
)

# Same volume but mounted at a different path inside the Suricata container.
DISABLE_CONF_CONTAINER_PATH = os.environ.get(
    "SURICATA_DISABLE_CONF_CONTAINER", "/etc/suricata/custom/disable.conf"
)

SURICATA_CONTAINER_NAME = os.environ.get(
    "SURICATA_CONTAINER_NAME", "raid_guard-suricata-1"
)

CONFIG_KEY = "disabled_rule_categories"

# ── ET Open category catalogue ────────────────────────────────────────────────

ET_OPEN_CATEGORIES: list[dict] = [
    {
        "id": "emerging-attack_response",
        "name": "Attack Response",
        "description": "Responses indicating a successful attack (e.g. id check returned root)",
    },
    {
        "id": "emerging-botcc",
        "name": "Botnet C&C",
        "description": "Connections to known botnet command & control servers",
    },
    {
        "id": "emerging-coinminer",
        "name": "Crypto Mining",
        "description": "Cryptocurrency mining traffic",
    },
    {
        "id": "emerging-current_events",
        "name": "Current Events",
        "description": "Rules tracking active campaigns and recent events",
    },
    {
        "id": "emerging-dns",
        "name": "DNS",
        "description": "DNS anomalies, tunneling, and DGA domains",
    },
    {
        "id": "emerging-dos",
        "name": "DoS",
        "description": "Denial-of-service attack signatures",
    },
    {
        "id": "emerging-drop",
        "name": "DROP / Spamhaus",
        "description": "Traffic to/from Spamhaus DROP-listed networks",
    },
    {
        "id": "emerging-exploit",
        "name": "Exploits",
        "description": "Exploit attempts and vulnerability scanning",
    },
    {
        "id": "emerging-ftp",
        "name": "FTP",
        "description": "FTP anomalies and exploits",
    },
    {
        "id": "emerging-icmp",
        "name": "ICMP",
        "description": "ICMP anomalies and covert channels",
    },
    {
        "id": "emerging-info",
        "name": "Informational",
        "description": "Low-priority informational rules; often noisy on home networks",
    },
    {
        "id": "emerging-ja3",
        "name": "JA3 TLS Fingerprints",
        "description": "Known malicious TLS client fingerprints",
    },
    {
        "id": "emerging-malware",
        "name": "Malware",
        "description": "Malware C2 traffic, payload delivery, and infections",
    },
    {
        "id": "emerging-misc",
        "name": "Miscellaneous",
        "description": "Threats that do not fit other categories",
    },
    {
        "id": "emerging-mobile_malware",
        "name": "Mobile Malware",
        "description": "Mobile device malware and C2 traffic",
    },
    {
        "id": "emerging-p2p",
        "name": "P2P",
        "description": "Peer-to-peer protocol traffic",
    },
    {
        "id": "emerging-phishing",
        "name": "Phishing",
        "description": "Phishing sites and credential-harvesting campaigns",
    },
    {
        "id": "emerging-policy",
        "name": "Policy",
        "description": "Acceptable-use policy violations; often noisy on home networks",
    },
    {
        "id": "emerging-scan",
        "name": "Scanning",
        "description": "Port scans, host discovery, and network reconnaissance",
    },
    {
        "id": "emerging-shellcode",
        "name": "Shellcode",
        "description": "Shellcode patterns in network traffic",
    },
    {
        "id": "emerging-smtp",
        "name": "SMTP",
        "description": "Email / SMTP anomalies",
    },
    {
        "id": "emerging-sql",
        "name": "SQL Injection",
        "description": "SQL injection attempts",
    },
    {
        "id": "emerging-trojan",
        "name": "Trojans",
        "description": "Trojan activity and RAT communication",
    },
    {
        "id": "emerging-user_agents",
        "name": "Malicious User-Agents",
        "description": "HTTP requests using known-malicious user agent strings",
    },
    {
        "id": "emerging-web_client",
        "name": "Web Client",
        "description": "Client-side web attacks (drive-by downloads, browser exploits)",
    },
    {
        "id": "emerging-web_server",
        "name": "Web Server",
        "description": "Server-side web attacks (injections, scanners)",
    },
    {
        "id": "emerging-worm",
        "name": "Worms",
        "description": "Worm propagation and self-spreading malware",
    },
]

_VALID_IDS: frozenset[str] = frozenset(c["id"] for c in ET_OPEN_CATEGORIES)


# ── Config table helpers ──────────────────────────────────────────────────────


async def get_disabled_categories(pool: asyncpg.Pool) -> list[str]:
    """Return the list of currently disabled ET Open category IDs from the DB."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM config WHERE key = $1", CONFIG_KEY
        )
    if not row:
        return []
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return []


async def set_disabled_categories(
    pool: asyncpg.Pool, disabled: list[str]
) -> None:
    """Persist the disabled category list to the DB and regenerate disable.conf.

    Raises ValueError for unknown category IDs.
    """
    unknown = [c for c in disabled if c not in _VALID_IDS]
    if unknown:
        raise ValueError(f"Unknown category IDs: {unknown}")

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO config(key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            CONFIG_KEY,
            json.dumps(sorted(disabled)),
        )

    _write_disable_conf(disabled)


# ── disable.conf management ───────────────────────────────────────────────────


def _write_disable_conf(disabled: list[str]) -> None:
    """Write (or remove) the suricata-update disable.conf file.

    An empty *disabled* list removes the file so suricata-update runs without
    the ``--disable-conf`` flag.
    """
    DISABLE_CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not disabled:
        DISABLE_CONF_PATH.unlink(missing_ok=True)
        logger.info("Removed disable.conf (all categories enabled)")
        return
    lines = ["# Generated by raid_guard — do not edit manually\n"]
    lines += [f"group:{cat}\n" for cat in sorted(disabled)]
    DISABLE_CONF_PATH.write_text("".join(lines))
    logger.info(
        "Wrote disable.conf: %d disabled categories: %s", len(disabled), sorted(disabled)
    )


# ── Suricata live reload ──────────────────────────────────────────────────────


def _reload_suricata_sync() -> str:
    """Run suricata-update inside the Suricata container then send SIGHUP.

    Uses the Docker SDK (requires /var/run/docker.sock mounted in the backend
    container).  Imported lazily so the module loads in unit-test environments
    where the socket is absent.

    Returns a human-readable status string.
    Raises RuntimeError on failure.
    """
    import docker  # noqa: PLC0415 — lazy import intentional
    import docker.errors  # noqa: PLC0415

    client = docker.from_env()
    try:
        container = client.containers.get(SURICATA_CONTAINER_NAME)
    except docker.errors.NotFound:
        raise RuntimeError(
            f"Suricata container '{SURICATA_CONTAINER_NAME}' not found. "
            "Set the SURICATA_CONTAINER_NAME environment variable to match the "
            "actual container name (check `docker ps`)."
        )

    cmd: list[str] = ["suricata-update", "--no-test"]
    if DISABLE_CONF_PATH.exists():
        cmd += ["--disable-conf", DISABLE_CONF_CONTAINER_PATH]

    logger.info("Reloading Suricata: exec %s in %s", cmd, SURICATA_CONTAINER_NAME)
    exit_code, output = container.exec_run(cmd, stderr=True)
    output_str = output.decode("utf-8", errors="replace") if output else ""

    if exit_code != 0:
        raise RuntimeError(
            f"suricata-update exited {exit_code}. Last output: {output_str[-400:]}"
        )

    # SIGHUP does not trigger rule reload in pcap/FIFO mode (it triggers shutdown
    # instead). Container restart is the only reliable apply mechanism.
    logger.info("Restarting %s to apply updated rules and threshold config", SURICATA_CONTAINER_NAME)
    container.restart(timeout=10)
    logger.info("%s restarted — rules and threshold config reloaded", SURICATA_CONTAINER_NAME)
    return "Rules updated and reloaded successfully."


async def reload_suricata() -> str:
    """Async wrapper — runs the synchronous Docker calls in a thread pool."""
    return await asyncio.to_thread(_reload_suricata_sync)


# ── Suppression management ────────────────────────────────────────────────────


def _append_suppression_sync(signature_id: int) -> None:
    """Append a Suricata suppress directive to suppress.conf (synchronous)."""
    SUPPRESS_CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"suppress gen_id 1, sig_id {signature_id}\n"
    with open(SUPPRESS_CONF_PATH, "a") as f:
        f.write(line)
    logger.info("Appended suppression for sig_id=%d to %s", signature_id, SUPPRESS_CONF_PATH)


async def apply_suppression(signature_id: int) -> None:
    """Write a suppress directive and trigger a live Suricata rule reload.

    Raises RuntimeError if the reload fails (same as ``reload_suricata``).
    """
    await asyncio.to_thread(_append_suppression_sync, signature_id)
    await reload_suricata()


# ── Threshold management ──────────────────────────────────────────────────────


def _append_threshold_sync(
    signature_id: int,
    count: int,
    seconds: int,
    track: str,
    type_: str,
) -> None:
    """Append a Suricata threshold directive to suppress.conf (synchronous).

    Both suppress and threshold directives live in the same file referenced by
    the ``threshold-file`` directive in suricata.yaml.
    """
    SUPPRESS_CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"threshold gen_id 1, sig_id {signature_id},"
        f" type {type_}, track {track},"
        f" count {count}, seconds {seconds}\n"
    )
    with open(SUPPRESS_CONF_PATH, "a") as f:
        f.write(line)
    logger.info(
        "Appended threshold for sig_id=%d (%s/%s count=%d seconds=%d) to %s",
        signature_id, type_, track, count, seconds, SUPPRESS_CONF_PATH,
    )


async def apply_threshold(
    signature_id: int,
    count: int,
    seconds: int,
    track: str = "by_src",
    type_: str = "limit",
) -> None:
    """Write a threshold directive and trigger a live Suricata rule reload.

    Raises RuntimeError if the reload fails.
    """
    await asyncio.to_thread(_append_threshold_sync, signature_id, count, seconds, track, type_)
    await reload_suricata()
