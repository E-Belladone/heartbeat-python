"""Debounce state machine: tailnet-online -> beat-worthy."""

from collections.abc import Iterable

from heartbeat.models import TailscaleDevice

__all__ = ["PresenceTracker"]


class PresenceTracker:
    """Tracks per-device online streaks against a debounce window.

    A device must be continuously online for `debounce` seconds before it
    earns beats; after that it is due on every poll until it drops offline,
    which resets the streak. This keeps heartbeat's last_seen fresh while a
    device is genuinely connected, without letting a flapping device spam
    beats. Time is injected (`now`) so the logic stays deterministic.
    """

    def __init__(self, debounce: float) -> None:
        self._debounce = debounce
        self._online_since: dict[str, float] = {}

    def update(self, devices: Iterable[TailscaleDevice], now: float) -> list[str]:
        """Record one poll result; return hostnames due for a beat."""
        due: list[str] = []
        seen: set[str] = set()
        for device in devices:
            seen.add(device.hostname)
            if not device.online:
                self._online_since.pop(device.hostname, None)
                continue
            since = self._online_since.setdefault(device.hostname, now)
            if now - since >= self._debounce:
                due.append(device.hostname)
        # a device that vanished from the status output is offline
        for hostname in set(self._online_since) - seen:
            del self._online_since[hostname]
        return due
