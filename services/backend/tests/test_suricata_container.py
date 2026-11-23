"""Suricata container lookup (name first, compose-label fallback) and the
status probe's state reporting."""

from unittest.mock import MagicMock, patch

import docker.errors
import pytest

from app.routers.status import _probe_suricata_sync
from app.suricata_container import SuricataContainerNotFound, find_suricata_container


def _container(name, project="raid_guard", running=True, health="healthy"):
    c = MagicMock()
    c.name = name
    c.labels = {"com.docker.compose.project": project, "com.docker.compose.service": "suricata"}
    c.attrs = {"State": {"Running": running, "Health": {"Status": health}}}
    return c


def _client(by_name=None, labelled=()):
    client = MagicMock()
    if by_name is None:
        client.containers.get.side_effect = docker.errors.NotFound("nope")
    else:
        client.containers.get.return_value = by_name
    client.containers.list.return_value = list(labelled)
    return client


def test_finds_container_by_configured_name():
    c = _container("raid_guard-suricata-1")
    client = _client(by_name=c)
    assert find_suricata_container(client) is c
    client.containers.list.assert_not_called()


def test_falls_back_to_compose_label_for_v1_naming():
    v1 = _container("raid_guard_suricata_1")
    client = _client(labelled=[v1])
    assert find_suricata_container(client) is v1
    client.containers.list.assert_called_once_with(
        all=True, filters={"label": "com.docker.compose.service=suricata"}
    )


def test_label_fallback_prefers_own_project():
    other = _container("other_suricata_1", project="other")
    ours = _container("raid_guard_suricata_1")
    assert find_suricata_container(_client(labelled=[other, ours])) is ours


def test_label_fallback_single_foreign_project_is_used():
    only = _container("custom_suricata_1", project="custom")
    assert find_suricata_container(_client(labelled=[only])) is only


def test_label_fallback_ambiguous_raises():
    a = _container("a_suricata_1", project="a")
    b = _container("b_suricata_1", project="b")
    with pytest.raises(SuricataContainerNotFound, match="several"):
        find_suricata_container(_client(labelled=[a, b]))


def test_no_container_raises_not_found():
    with pytest.raises(SuricataContainerNotFound):
        find_suricata_container(_client())


# ── _probe_suricata_sync ──────────────────────────────────────────────────────

def _probe_with(client):
    with patch("docker.from_env", return_value=client):
        return _probe_suricata_sync()


def test_probe_running_via_label_fallback():
    result = _probe_with(_client(labelled=[_container("raid_guard_suricata_1")]))
    assert result["ok"] is True
    assert result["state"] == "running"
    assert result["container"] == "raid_guard_suricata_1"


def test_probe_stopped_container():
    result = _probe_with(_client(by_name=_container("x", running=False, health="unhealthy")))
    assert result["ok"] is False
    assert result["state"] == "stopped"


def test_probe_not_found_is_not_reported_as_stopped():
    result = _probe_with(_client())
    assert result["ok"] is False
    assert result["state"] == "not_found"
    assert "SURICATA_CONTAINER_NAME" in result["message"]


def test_probe_docker_error():
    with patch("docker.from_env", side_effect=docker.errors.DockerException("socket gone")):
        result = _probe_suricata_sync()
    assert result["ok"] is False
    assert result["state"] == "error"
    assert "socket gone" in result["message"]
