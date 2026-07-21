"""Read device presence from the local tailscaled."""

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from heartbeat.models import TailscaleDevice

__all__ = ["DEFAULT_CMD", "TailscaleError", "get_status", "parse_status"]

DEFAULT_CMD: tuple[str, ...] = ("tailscale", "status", "--json")


class TailscaleError(RuntimeError):
    """`tailscale status` failed or returned something unparseable."""


def parse_status(payload: dict[str, Any]) -> list[TailscaleDevice]:
    """Extract Self plus all peers from a `tailscale status --json` payload."""
    nodes: list[dict[str, Any]] = []
    self_node = payload.get("Self")
    if self_node:
        nodes.append(self_node)
    nodes.extend((payload.get("Peer") or {}).values())
    try:
        return [TailscaleDevice.model_validate(node) for node in nodes]
    except ValidationError as e:
        raise TailscaleError(f"unexpected tailscale status shape: {e}") from e


async def get_status(
    cmd: Sequence[str] = DEFAULT_CMD, timeout: float = 10.0
) -> list[TailscaleDevice]:
    """Run `tailscale status --json` and parse the device list."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError as e:
        proc.kill()
        raise TailscaleError(f"tailscale status timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise TailscaleError(
            f"tailscale status exited {proc.returncode}: {stderr.decode(errors='replace').strip()}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise TailscaleError("tailscale status produced invalid JSON") from e
    return parse_status(payload)
