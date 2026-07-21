from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from fakes import FakePresenceSource
from heartbeat.config import ProxySettings
from heartbeat.proxy.app import create_app
from heartbeat.proxy.presence import PresenceSnapshot, SourceState

NOW = 1_800_000_000.0

SETTINGS = ProxySettings(dsn=SecretStr("postgres://unused"), online_threshold=150, cache_ttl=5.0)

SNAPSHOT = PresenceSnapshot(
    last_seen=int(NOW) - 42, longest_absence=86_400, total_beats=99_999, device_count=3
)


def make_client(source: FakePresenceSource, clock: list[float]) -> httpx.AsyncClient:
    app = create_app(SETTINGS, source=source, now_fn=lambda: clock[0])
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://public.test")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(FakePresenceSource(SNAPSHOT), [NOW]) as c:
        yield c


async def test_presence_returns_aggregate(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/presence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["last_seen_relative"] == 42
    assert body["total_beats"] == 99_999


async def test_presence_shape_never_contains_device_data(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/presence")).json()
    assert set(body) == {
        "online",
        "activity",  # aggregated tier from unlabeled kind+age pairs: reviewed, no identity
        "last_seen",
        "last_seen_relative",
        "longest_absence",
        "total_beats",
        "device_count",  # a bare count: reviewed against invariant #1, carries no identity
        "total_strong_signals",  # a bare count over unlabeled events: reviewed, no identity
        "last_strong_signal",  # max timestamp across all sources: reviewed, no identity
        "last_strong_signal_relative",
        "uptime",
    }


async def test_activity_reflects_signal_engagement() -> None:
    engaged = SNAPSHOT.model_copy(
        update={"source_states": [SourceState(kind="start", at=int(NOW) - 60)]}
    )
    async with make_client(FakePresenceSource(engaged), [NOW]) as c:
        assert (await c.get("/api/presence")).json()["activity"] == "active"
    async with make_client(FakePresenceSource(SNAPSHOT), [NOW]) as c:
        # online with no engaged signal source: merely around
        assert (await c.get("/api/presence")).json()["activity"] == "around"


async def test_snapshot_is_cached_within_ttl() -> None:
    source = FakePresenceSource(SNAPSHOT)
    clock = [NOW]
    async with make_client(source, clock) as c:
        await c.get("/api/presence")
        clock[0] = NOW + 2  # inside the 5 s ttl
        await c.get("/api/presence")
        assert source.calls == 1
        clock[0] = NOW + 10  # past the ttl
        resp = await c.get("/api/presence")
        assert source.calls == 2
        # uptime moved with the clock
        assert resp.json()["uptime"] == 10


async def test_database_failure_is_an_opaque_503() -> None:
    source = FakePresenceSource(SNAPSHOT)
    source.fail = True
    async with make_client(source, [NOW]) as c:
        resp = await c.get("/api/presence")
    assert resp.status_code == 503
    assert "pg" not in resp.text.lower()
    assert "connection" not in resp.text.lower()


async def test_badge_serves_svg_for_each_metric(client: httpx.AsyncClient) -> None:
    for metric in ("status", "last-seen", "beats"):
        resp = await client.get(f"/api/badge/{metric}.svg")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/svg+xml")
        assert resp.text.startswith("<svg")
    # the online aggregate reads as "around" and beats humanise to a count
    assert "around" in (await client.get("/api/badge/status.svg")).text
    assert "100k" in (await client.get("/api/badge/beats.svg")).text  # 99_999 rounds up


async def test_badge_unknown_metric_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/badge/bogus.svg")).status_code == 404


async def test_badge_degrades_to_unavailable_on_db_failure() -> None:
    # decorative embed: a snapshot failure must still render an image, not 503
    source = FakePresenceSource(SNAPSHOT)
    source.fail = True
    async with make_client(source, [NOW]) as c:
        resp = await c.get("/api/badge/status.svg")
    assert resp.status_code == 200
    assert "unavailable" in resp.text


async def test_healthz(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_api_docs_are_disabled(client: httpx.AsyncClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await client.get(path)).status_code == 404


# --- websocket presence (M5) ---
# starlette's TestClient drives the websocket in-process; sync on purpose.
# `with TestClient(app)` runs the app lifespan, which starts the broadcast
# pump + the NOTIFY listener — real serving (uvicorn) runs it the same way.

WS_SETTINGS = ProxySettings(
    dsn=SecretStr("postgres://unused"),
    online_threshold=150,
    cache_ttl=0.0,  # no caching: every tick recomputes from the source
    ws_interval=0.01,
)


def make_ws_client(source: FakePresenceSource, clock: list[float]) -> TestClient:
    return TestClient(create_app(WS_SETTINGS, source=source, now_fn=lambda: clock[0]))


def test_ws_pushes_the_aggregate_every_tick() -> None:
    with (
        make_ws_client(FakePresenceSource(SNAPSHOT), [NOW]) as client,
        client.websocket_connect("/api/presence/ws") as ws,
    ):
        first = ws.receive_json()
        assert first["online"] is True
        assert first["total_beats"] == 99_999
        # the next tick arrives without any client action (also the keepalive)
        assert ws.receive_json()["total_beats"] == 99_999


def test_ws_payload_shape_matches_the_pinned_public_surface() -> None:
    with (
        make_ws_client(FakePresenceSource(SNAPSHOT), [NOW]) as client,
        client.websocket_connect("/api/presence/ws") as ws,
    ):
        assert set(ws.receive_json()) == {
            "online",
            "activity",
            "last_seen",
            "last_seen_relative",
            "longest_absence",
            "total_beats",
            "device_count",
            "total_strong_signals",
            "last_strong_signal",
            "last_strong_signal_relative",
            "uptime",
        }


def test_ws_survives_a_database_hiccup() -> None:
    source = FakePresenceSource(SNAPSHOT)
    with (
        make_ws_client(source, [NOW]) as client,
        client.websocket_connect("/api/presence/ws") as ws,
    ):
        assert ws.receive_json()["online"] is True
        source.fail = True  # ticks pass silently, the socket stays open
        source.set_snapshot(SNAPSHOT.model_copy(update={"total_beats": 100_000}))
        source.fail = False
        # only a post-recovery fetch can carry the new count; frames from
        # before the outage may still sit buffered, so drain a few
        assert any(ws.receive_json()["total_beats"] == 100_000 for _ in range(10))


def test_ws_pushes_immediately_on_notify() -> None:
    # a NOTIFY (poller beat / ingest signal) forces a fresh push at once, not
    # on the next timer tick; the payload reflects the source's new state
    source = FakePresenceSource(SNAPSHOT)
    with (
        make_ws_client(source, [NOW]) as client,
        client.websocket_connect("/api/presence/ws") as ws,
    ):
        assert ws.receive_json()["total_beats"] == 99_999
        source.set_snapshot(SNAPSHOT.model_copy(update={"total_beats": 100_000}))
        source.notify()
        # drain until the new value lands (a timer tick may race ahead of it)
        seen = {ws.receive_json()["total_beats"] for _ in range(3)}
        assert 100_000 in seen
