"""In-memory test doubles for the presence proxy and the signal ingest service."""

from collections.abc import Awaitable, Callable

from heartbeat.ingest.store import IngestToken, RecordedSignal
from heartbeat.proxy.presence import PresenceSnapshot


class FakePresenceSource:
    def __init__(self, snapshot: PresenceSnapshot) -> None:
        self._snapshot = snapshot
        self.calls = 0
        self.fail = False
        self.video: str | None = None
        self._on_change: Callable[[], None] | None = None

    async def snapshot(self) -> PresenceSnapshot:
        self.calls += 1
        if self.fail:
            raise ConnectionError("pg down")
        return self._snapshot

    def set_snapshot(self, snapshot: PresenceSnapshot) -> None:
        """Swap the snapshot a later fetch/notify will report (test helper)."""
        self._snapshot = snapshot

    async def random_video(self) -> str | None:
        if self.fail:
            raise ConnectionError("pg down")
        return self.video

    async def listen(self, on_change: Callable[[], None]) -> Callable[[], Awaitable[None]]:
        self._on_change = on_change

        async def unlisten() -> None:
            self._on_change = None

        return unlisten

    def notify(self) -> None:
        """Simulate a NOTIFY reaching the proxy (test helper)."""
        if self._on_change is not None:
            self._on_change()

    async def close(self) -> None:
        pass


class InMemorySignalStore:
    """Keyed by token digest, like the real lookup; revoked = absent."""

    def __init__(self, tokens: dict[str, IngestToken] | None = None, *, now: int = 0) -> None:
        self.tokens = tokens or {}
        self.now = now
        self.events: list[tuple[int, str, str]] = []
        self.fail = False

    async def token_by_digest(self, digest: str) -> IngestToken | None:
        if self.fail:
            raise ConnectionError("pg down")
        return self.tokens.get(digest)

    async def record(self, *, token_id: int, source: str, kind: str) -> RecordedSignal:
        self.events.append((token_id, source, kind))
        return RecordedSignal(id=len(self.events), at=self.now)
