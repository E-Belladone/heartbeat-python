"""API tests for the signal ingest service (fake store; real store in
test_pg_integration.py)."""

import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from fakes import InMemorySignalStore
from heartbeat.config import IngestSettings
from heartbeat.ingest.app import create_app
from heartbeat.ingest.store import IngestToken

SETTINGS = IngestSettings(dsn=SecretStr("postgres://unused"))
PHONE_TOKEN = "phone-secret"
NOW = 1_800_000_000


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@pytest.fixture
def store() -> InMemorySignalStore:
    return InMemorySignalStore(
        {digest(PHONE_TOKEN): IngestToken(id=1, device="phone", sources=frozenset({"phone-lock"}))},
        now=NOW,
    )


@pytest.fixture
async def client(store: InMemorySignalStore) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS, store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://tailnet.test") as c:
        yield c


async def test_healthz_needs_no_token(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200


async def test_push_requires_a_known_token(client: httpx.AsyncClient) -> None:
    body = {"source": "phone-lock", "kind": "pulse"}
    assert (await client.post("/api/signal", json=body)).status_code == 401
    resp = await client.post("/api/signal", json=body, headers={"Authorization": "not-the-token"})
    assert resp.status_code == 401


async def test_push_rejects_sources_outside_the_token_allowlist(
    client: httpx.AsyncClient, store: InMemorySignalStore
) -> None:
    resp = await client.post(
        "/api/signal",
        json={"source": "windows-lock", "kind": "pulse"},
        headers={"Authorization": PHONE_TOKEN},
    )
    assert resp.status_code == 403
    assert store.events == []


async def test_push_rejects_unknown_kinds(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/signal",
        json={"source": "phone-lock", "kind": "blip"},
        headers={"Authorization": PHONE_TOKEN},
    )
    assert resp.status_code == 422


async def test_push_records_and_attributes(
    client: httpx.AsyncClient, store: InMemorySignalStore
) -> None:
    resp = await client.post(
        "/api/signal",
        json={"source": "phone-lock", "kind": "start"},
        headers={"Authorization": PHONE_TOKEN},
    )
    assert resp.status_code == 201
    assert resp.json() == {
        "id": 1,
        "device": "phone",
        "source": "phone-lock",
        "kind": "start",
        "at": NOW,
    }
    assert store.events == [(1, "phone-lock", "start")]


async def test_push_normalizes_the_source(
    client: httpx.AsyncClient, store: InMemorySignalStore
) -> None:
    resp = await client.post(
        "/api/signal",
        json={"source": "  Phone-Lock ", "kind": "stop"},
        headers={"Authorization": PHONE_TOKEN},
    )
    assert resp.status_code == 201
    assert store.events == [(1, "phone-lock", "stop")]


async def test_store_outage_is_an_opaque_503(
    client: httpx.AsyncClient, store: InMemorySignalStore
) -> None:
    store.fail = True
    resp = await client.post(
        "/api/signal",
        json={"source": "phone-lock", "kind": "pulse"},
        headers={"Authorization": PHONE_TOKEN},
    )
    assert resp.status_code == 503
    assert "pg" not in resp.text.lower()
