"""Shared data models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["PublicPresence", "TailscaleDevice"]


class TailscaleDevice(BaseModel):
    """One device as reported by `tailscale status --json` (Self or a Peer entry)."""

    model_config = ConfigDict(populate_by_name=True)

    hostname: str = Field(alias="HostName")
    online: bool = Field(alias="Online")


class PublicPresence(BaseModel):
    """The only presence shape allowed to leave the tailnet.

    Privacy invariant: aggregate signal only. No device names, ids,
    hostnames, or per-device timestamps, ever. Extend with care.
    """

    online: bool
    activity: Literal["active", "around", "away"]
    """Aggregated tier (M18): a strong signal fired recently (active),
    devices are merely reachable (around), or neither (away). Computed
    from unlabeled kind+age pairs; never per-device, never per-source."""
    last_seen: int | None
    last_seen_relative: int
    longest_absence: int
    total_beats: int
    device_count: int
    """How many devices feed the heartbeat (a bare count, never which)."""
    total_strong_signals: int
    """How many strong signals (start/pulse) ever arrived; a bare count,
    never which device or source pushed them."""
    last_strong_signal: int | None
    """Unix seconds of the most recent strong signal, across all sources."""
    last_strong_signal_relative: int
    uptime: int
