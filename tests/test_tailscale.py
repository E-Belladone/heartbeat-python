import json
import sys
from typing import Any

import pytest

from heartbeat.tailscale import TailscaleError, get_status, parse_status


def test_parse_status_extracts_self_and_peers(tailscale_status: dict[str, Any]) -> None:
    devices = {d.hostname: d.online for d in parse_status(tailscale_status)}
    assert devices == {"odroid": True, "laptop": True, "phone": False}


def test_parse_status_handles_null_peer_map(tailscale_status: dict[str, Any]) -> None:
    tailscale_status["Peer"] = None
    devices = parse_status(tailscale_status)
    assert [d.hostname for d in devices] == ["odroid"]


def test_parse_status_rejects_malformed_nodes() -> None:
    with pytest.raises(TailscaleError):
        parse_status({"Self": {"HostName": "x"}})  # missing Online


async def test_get_status_runs_command(tailscale_status: dict[str, Any]) -> None:
    payload = json.dumps(tailscale_status)
    cmd = (sys.executable, "-c", f"print({payload!r})")
    devices = await get_status(cmd=cmd)
    assert len(devices) == 3


async def test_get_status_failure_raises() -> None:
    cmd = (sys.executable, "-c", "import sys; sys.exit(1)")
    with pytest.raises(TailscaleError, match="exited 1"):
        await get_status(cmd=cmd)


async def test_get_status_invalid_json_raises() -> None:
    cmd = (sys.executable, "-c", "print('not json')")
    with pytest.raises(TailscaleError, match="invalid JSON"):
        await get_status(cmd=cmd)
