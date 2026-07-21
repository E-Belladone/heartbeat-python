"""Tailnet-only FastAPI service accepting device-pushed signals (M17).

Defense in depth: deployment keeps this off the public vhost (tailnet bind
only), and every push needs a per-device token from signal.tokens — sent
raw in the Authorization header like the logger's shared token, but looked
up by sha256 digest, so the plaintext exists only on the device. Events
are server-stamped on arrival: clients stay dumb (no clocks, no
buffering), offline events are dropped by design, and spans are derived
downstream (M18), never here.
"""

import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException

from heartbeat.config import IngestSettings
from heartbeat.ingest.models import SignalRequest, SignalResponse
from heartbeat.ingest.store import IngestToken, PostgresSignalStore, SignalStorage

__all__ = ["create_app", "main"]

log = logging.getLogger("heartbeat.ingest")


def create_app(
    settings: IngestSettings | None = None, *, store: SignalStorage | None = None
) -> FastAPI:
    """Build the ingest app; the store is injectable for tests."""
    cfg = settings or IngestSettings()
    owns_store = store is None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal store
        if owns_store:
            store = await PostgresSignalStore.connect(cfg.dsn.get_secret_value())
        try:
            yield
        finally:
            if owns_store and isinstance(store, PostgresSignalStore):
                await store.close()

    def get_store() -> SignalStorage:
        if store is None:  # lifespan not started; unreachable in normal serving
            raise HTTPException(status_code=503, detail="store not ready")
        return store

    async def authenticate(
        authorization: Annotated[str | None, Header()] = None,
    ) -> IngestToken:
        if not authorization:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        digest = hashlib.sha256(authorization.encode()).hexdigest()
        try:
            token = await get_store().token_by_digest(digest)
        except Exception as e:  # pg down: opaque to the client, details in logs
            log.warning("token lookup failed: %s", e.__class__.__name__)
            raise HTTPException(status_code=503, detail="token lookup unavailable") from e
        if token is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        return token

    app = FastAPI(
        title="heartbeat signal ingest",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.post("/api/signal", status_code=201)
    async def push_signal(
        req: SignalRequest, token: Annotated[IngestToken, Depends(authenticate)]
    ) -> SignalResponse:
        source = req.source.strip().lower()
        if source not in token.sources:
            # authenticated but outside the token's allowlist is 403: a retry
            # with the same credential cannot help
            raise HTTPException(status_code=403, detail=f"token may not report {source}")
        recorded = await get_store().record(token_id=token.id, source=source, kind=req.kind)
        log.info("signal %s/%s from %s", source, req.kind, token.device)
        return SignalResponse(
            id=recorded.id, device=token.device, source=source, kind=req.kind, at=recorded.at
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = IngestSettings()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
