"""Write presence data: the device registry and the beat stream.

The poller is the single writer of presence data. Every device seen on the
tailnet self-registers (hostname, first_seen, last_seen); only devices with
tracked = true get beats, and tracking is toggled from the dashboard, not
from config. Everything the public site shows (last seen, total beats,
longest absence) is computed from the beat rows at read time, so there are
no counters to keep in sync.
"""

import logging
from collections.abc import Sequence
from typing import Protocol

import asyncpg

from heartbeat.models import TailscaleDevice
from heartbeat.notify import PRESENCE_CHANNEL

__all__ = ["BeatSink", "PostgresBeatSink"]

log = logging.getLogger("heartbeat.poller")


class BeatSink(Protocol):
    """What the poll loop needs (injectable in tests)."""

    async def sync_devices(self, devices: Sequence[TailscaleDevice], now: float) -> frozenset[str]:
        """Register every seen device, stamp last_seen for the online ones,
        and return the hostnames currently tracked."""
        ...

    async def beat(self, hostname: str, now: float) -> None: ...
    async def close(self) -> None: ...


class PostgresBeatSink:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._device_ids: dict[str, int] = {}

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=0, max_size=2)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresBeatSink.connect() was not called")
        return self._pool

    async def sync_devices(self, devices: Sequence[TailscaleDevice], now: float) -> frozenset[str]:
        pool = self._require_pool()
        seen = [d.hostname for d in devices]
        online = [d.hostname for d in devices if d.online]
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO presence.devices (hostname)"
                " SELECT unnest($1::text[]) ON CONFLICT (hostname) DO NOTHING",
                seen,
            )
            await conn.execute(
                "UPDATE presence.devices SET last_seen = to_timestamp($2)"
                " WHERE hostname = ANY($1::text[])",
                online,
                now,
            )
            rows = await conn.fetch("SELECT hostname FROM presence.devices WHERE tracked")
        return frozenset(r["hostname"] for r in rows)

    async def _device_id(self, hostname: str) -> int:
        if hostname not in self._device_ids:
            pool = self._require_pool()
            device_id = await pool.fetchval(
                "INSERT INTO presence.devices (hostname) VALUES ($1)"
                " ON CONFLICT (hostname) DO UPDATE SET hostname = EXCLUDED.hostname"
                " RETURNING id",
                hostname,
            )
            self._device_ids[hostname] = int(device_id)
        return self._device_ids[hostname]

    async def beat(self, hostname: str, now: float) -> None:
        device_id = await self._device_id(hostname)
        async with self._require_pool().acquire() as conn:
            await conn.execute(
                "INSERT INTO presence.beats (device, beat_at)"
                " VALUES ($1, to_timestamp($2)) ON CONFLICT DO NOTHING",
                device_id,
                now,
            )
            # wake the proxy so open sockets see the new beat at once (M5);
            # payload is a coarse tag, never the hostname (invariant #1).
            # best-effort: the beat has committed, the proxy's timer covers a
            # missed notify, so a notify hiccup must not fail the write
            try:
                await conn.execute("SELECT pg_notify($1, $2)", PRESENCE_CHANNEL, "beat")
            except Exception as e:
                log.warning("presence notify failed: %s", e.__class__.__name__)
