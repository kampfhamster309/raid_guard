"""
Locate the Suricata container via the Docker API.

The container name depends on which Compose implementation started the stack:
Compose v2+ uses ``<project>-suricata-1`` while legacy ``docker-compose`` v1
uses ``<project>_suricata_1``. A name-only lookup silently breaks when the
"other" tool is used, so we try the configured name first and then fall back
to the ``com.docker.compose.service=suricata`` label, which both
implementations set.
"""

import logging
import os

logger = logging.getLogger(__name__)

SURICATA_CONTAINER_NAME = os.environ.get(
    "SURICATA_CONTAINER_NAME", "raid_guard-suricata-1"
)
COMPOSE_PROJECT_NAME = os.environ.get("COMPOSE_PROJECT_NAME", "raid_guard")
_SERVICE_LABEL = "com.docker.compose.service"
_PROJECT_LABEL = "com.docker.compose.project"


class SuricataContainerNotFound(LookupError):
    """No container matched the configured name or the compose service label."""


def find_suricata_container(client):
    """Return the Suricata container object, or raise SuricataContainerNotFound.

    Docker connection errors propagate unchanged so callers can tell
    "socket unreachable" apart from "container missing".
    """
    import docker.errors  # noqa: PLC0415 — lazy import, see rule_manager

    try:
        return client.containers.get(SURICATA_CONTAINER_NAME)
    except docker.errors.NotFound:
        pass

    candidates = client.containers.list(
        all=True, filters={"label": f"{_SERVICE_LABEL}=suricata"}
    )
    if not candidates:
        raise SuricataContainerNotFound(
            f"No Suricata container found: no container named "
            f"'{SURICATA_CONTAINER_NAME}' and none labelled "
            f"{_SERVICE_LABEL}=suricata. Check `docker ps` and set "
            f"SURICATA_CONTAINER_NAME."
        )

    # Several compose projects could each run a suricata service; prefer ours.
    same_project = [
        c for c in candidates
        if c.labels.get(_PROJECT_LABEL) == COMPOSE_PROJECT_NAME
    ]
    if same_project:
        chosen = same_project[0]
    elif len(candidates) == 1:
        chosen = candidates[0]
    else:
        names = ", ".join(c.name for c in candidates)
        raise SuricataContainerNotFound(
            f"Container '{SURICATA_CONTAINER_NAME}' not found and several "
            f"suricata service containers exist ({names}); set "
            f"SURICATA_CONTAINER_NAME to pick one."
        )

    logger.debug(
        "Suricata container '%s' not found by name; using '%s' (label match)",
        SURICATA_CONTAINER_NAME, chosen.name,
    )
    return chosen
