"""Read the aggregate presence snapshot from the presence database.

Aggregates only, by construction *and* by grant: every query reads a
label-free view (`presence.stats`, `signal.source_state`,
`signal.strong_stats`) and the proxy role holds no SELECT on the base
tables, so nothing device-identifying can reach the proxy process even
through a buggy query (privacy invariant #1).
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

import asyncpg
from pydantic import BaseModel

from heartbeat.notify import PRESENCE_CHANNEL

__all__ = ["PostgresPresence", "PresenceSnapshot", "PresenceSource", "SourceState"]

log = logging.getLogger("heartbeat.proxy")


class SourceState(BaseModel):
    """Latest event of one signal source: kind + timestamp, no labels.

    Which device or source it was never leaves the database; kind and age
    are all the activity algebra needs (aggregate.py).
    """

    kind: str
    at: int


class PresenceSnapshot(BaseModel):
    last_seen: int | None
    """Unix seconds of the most recent beat, across all devices."""
    longest_absence: int
    """Longest gap (seconds) between consecutive beats in history."""
    total_beats: int
    device_count: int
    """How many devices are tracked (a bare count; nothing identifying)."""
    source_states: list[SourceState] = []
    """Unlabeled latest-per-source signal states (M18); empty when the
    signal schema isn't rolled out yet — the tailscale baseline carries."""
    strong_total: int = 0
    """How many strong signals (start/pulse) ever arrived; a bare count."""
    strong_last: int | None = None
    """Unix seconds of the most recent strong signal, across all sources."""


class PresenceSource(Protocol):
    async def snapshot(self) -> PresenceSnapshot: ...

    async def random_video(self) -> str | None:
        """One random youtube id from the curated crate; None when empty."""
        ...

    async def listen(self, on_change: Callable[[], None]) -> Callable[[], Awaitable[None]]:
        """Fire on_change once per presence NOTIFY; return an unlisten coroutine.

        on_change runs in the event loop and must be cheap and non-blocking
        (set a flag / event); the proxy does the actual recompute. May raise
        when a live listener can't be established — the proxy then degrades to
        its timer heartbeat, so a missing listener never breaks presence.
        """
        ...

    async def close(self) -> None: ...


# the whole snapshot behind one label-free view; the gap scan lives in the
# view definition (schema.sql), still behind the proxy's cache. The proxy
# role can't SELECT the base tables, so this is the only shape possible.
_SNAPSHOT_SQL = """
SELECT last_seen, total_beats, device_count, longest_absence FROM presence.stats
"""


class PostgresPresence:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=0, max_size=2)
        return self._pool

    async def random_video(self) -> str | None:
        pool = await self._get_pool()
        try:
            video: str | None = await pool.fetchval(
                "SELECT youtube_id FROM site.videos ORDER BY random() LIMIT 1"
            )
        except (asyncpg.UndefinedTableError, asyncpg.InsufficientPrivilegeError) as e:
            # table or grant not rolled out yet: the embed is decorative
            log.warning("video crate unavailable: %s", e.__class__.__name__)
            return None
        return video

    async def snapshot(self) -> PresenceSnapshot:
        pool = await self._get_pool()
        row = await pool.fetchrow(_SNAPSHOT_SQL)
        assert row is not None  # noqa: S101 - aggregate query always yields one row
        try:
            states = await pool.fetch(
                "SELECT kind, extract(epoch FROM at)::bigint AS at FROM signal.source_state"
            )
        except (asyncpg.UndefinedTableError, asyncpg.InsufficientPrivilegeError) as e:
            # view or grant not rolled out yet: signals are additive, the
            # tailscale baseline must keep presence alive (M18)
            log.warning("signal state unavailable: %s", e.__class__.__name__)
            states = []
        strong_total, strong_last = 0, None
        try:
            strong = await pool.fetchrow(
                "SELECT strong_total, strong_last FROM signal.strong_stats"
            )
            if strong is not None:
                strong_total, strong_last = strong["strong_total"], strong["strong_last"]
        except (asyncpg.UndefinedTableError, asyncpg.InsufficientPrivilegeError) as e:
            # same rollout tolerance as source_state above
            log.warning("strong-signal stats unavailable: %s", e.__class__.__name__)
        return PresenceSnapshot(
            last_seen=row["last_seen"],
            longest_absence=row["longest_absence"],
            total_beats=row["total_beats"],
            device_count=row["device_count"],
            source_states=[SourceState(kind=s["kind"], at=s["at"]) for s in states],
            strong_total=strong_total,
            strong_last=strong_last,
        )

    async def listen(self, on_change: Callable[[], None]) -> Callable[[], Awaitable[None]]:
        # a dedicated connection outside the query pool: LISTEN holds it open
        # for the process lifetime, and mixing it with pooled queries risks
        # the notification connection being handed out mid-query
        conn = await asyncpg.connect(self._dsn)

        def _on_notify(*_: object) -> None:
            on_change()

        def _on_terminate(_: object) -> None:
            # asyncpg does not auto-reconnect a LISTEN connection; if the backend
            # dies (pg restart, network blip) instant push pauses until the
            # proxy restarts. Log it so the silent switch to timer-only is
            # visible; presence itself keeps working on the timer keepalive.
            log.warning(
                "presence LISTEN connection lost; instant push paused, timer keepalive holds"
            )

        conn.add_termination_listener(_on_terminate)
        await conn.add_listener(PRESENCE_CHANNEL, _on_notify)

        async def unlisten() -> None:
            try:
                await conn.remove_listener(PRESENCE_CHANNEL, _on_notify)
            finally:
                await conn.close()

        return unlisten

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
