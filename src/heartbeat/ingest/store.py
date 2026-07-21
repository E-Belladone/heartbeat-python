"""Postgres persistence for pushed signals (signal.* schema)."""

import logging
from dataclasses import dataclass
from typing import Protocol, Self

import asyncpg

from heartbeat.notify import PRESENCE_CHANNEL

__all__ = ["IngestToken", "PostgresSignalStore", "RecordedSignal", "SignalStorage"]

log = logging.getLogger("heartbeat.ingest")


@dataclass(frozen=True)
class IngestToken:
    """A resolved per-device credential (signal.tokens row, minus the digest)."""

    id: int
    device: str
    sources: frozenset[str]


@dataclass(frozen=True)
class RecordedSignal:
    id: int
    at: int
    """Epoch seconds, stamped by the database on arrival."""


class SignalStorage(Protocol):
    """What the API needs from the store (in-memory fake in tests)."""

    async def token_by_digest(self, digest: str) -> IngestToken | None: ...
    async def record(self, *, token_id: int, source: str, kind: str) -> RecordedSignal: ...


class PostgresSignalStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> Self:
        return cls(await asyncpg.create_pool(dsn, min_size=0, max_size=4))

    async def close(self) -> None:
        await self.pool.close()

    async def token_by_digest(self, digest: str) -> IngestToken | None:
        """Resolve an active token by its sha256 digest; revoked ones vanish."""
        row = await self.pool.fetchrow(
            "SELECT id, device, sources FROM signal.tokens"
            " WHERE token_sha256 = $1 AND revoked_at IS NULL",
            digest,
        )
        if row is None:
            return None
        return IngestToken(id=row["id"], device=row["device"], sources=frozenset(row["sources"]))

    async def record(self, *, token_id: int, source: str, kind: str) -> RecordedSignal:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO signal.events (token, source, kind) VALUES ($1, $2, $3)"
                " RETURNING id, extract(epoch FROM at)::bigint AS at",
                token_id,
                source,
                kind,
            )
            assert row is not None  # noqa: S101 - INSERT .. RETURNING always yields a row
            # wake the proxy so the activity tier updates at once (M5); the
            # payload is a coarse tag, never the device or source (invariant #1).
            # best-effort: the event has committed, so a failed notify must not
            # turn into a 500 that has the device retry and double-insert (there
            # is no dedup on signal.events) — the proxy's timer covers the miss
            try:
                await conn.execute("SELECT pg_notify($1, $2)", PRESENCE_CHANNEL, "signal")
            except Exception as e:
                log.warning("presence notify failed: %s", e.__class__.__name__)
        return RecordedSignal(id=row["id"], at=row["at"])
