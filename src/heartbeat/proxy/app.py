"""FastAPI app exposing the aggregate presence signal to the public site."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, HTTPException, Response, WebSocket

from heartbeat.config import ProxySettings
from heartbeat.models import PublicPresence
from heartbeat.proxy import badge
from heartbeat.proxy.aggregate import aggregate
from heartbeat.proxy.presence import PostgresPresence, PresenceSource

__all__ = ["create_app", "main"]

log = logging.getLogger("heartbeat.proxy")


def create_app(
    settings: ProxySettings | None = None,
    source: PresenceSource | None = None,
    now_fn: Callable[[], float] = time.time,
) -> FastAPI:
    """Build the proxy app; the presence source and clock are injectable."""
    cfg = settings or ProxySettings()
    if source is None:
        source = PostgresPresence(cfg.dsn.get_secret_value())
    started = now_fn()
    cached: tuple[float, PublicPresence] | None = None

    # every open websocket holds a small queue; the pump fans one recomputed
    # payload out to all of them, so N sockets cost one snapshot, not N
    subscribers: set[asyncio.Queue[str]] = set()
    dirty = asyncio.Event()

    async def current(force: bool = False) -> PublicPresence:
        """The aggregate, cache-served unless `force`; raises what the source raises."""
        nonlocal cached
        now = now_fn()
        if not force and cached is not None and now - cached[0] < cfg.cache_ttl:
            return cached[1]
        snapshot = await source.snapshot()
        result = aggregate(
            snapshot,
            now=now,
            uptime=now - started,
            online_threshold=cfg.online_threshold,
            session_timeout=cfg.active_session_timeout,
            pulse_window=cfg.active_pulse_window,
        )
        cached = (now, result)
        return result

    async def broadcast(force: bool) -> None:
        """Push one freshly-aggregated payload to every open socket."""
        if not subscribers:
            return  # nobody watching: no snapshot, so idle load stays at zero
        try:
            payload = (await current(force=force)).model_dump_json()
        except Exception as e:
            # db hiccup: keep the sockets, clients keep their last value
            log.warning("presence snapshot failed: %s", e.__class__.__name__)
            return
        for q in subscribers:
            if q.full():
                with suppress(asyncio.QueueEmpty):
                    q.get_nowait()  # drop the stale value a slow client hasn't read
            with suppress(asyncio.QueueFull):
                q.put_nowait(payload)

    async def pump() -> None:
        """Broadcast on every NOTIFY and on a timer keepalive between them.

        Both paths recompute: a NOTIFY so state changes land at once, the timer
        so server-computed relative times (last_seen, uptime) stay fresh and the
        socket gets its keepalive. Forcing is safe because broadcast() no-ops
        when nobody is watching, so an unwatched proxy still does zero work; the
        REST cache (cache_ttl) is what absorbs request bursts, not this loop.
        """
        while True:
            with suppress(TimeoutError):
                await asyncio.wait_for(dirty.wait(), timeout=cfg.ws_interval)
            dirty.clear()
            await broadcast(force=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        pump_task = asyncio.create_task(pump())
        unlisten: Callable[[], Awaitable[None]] | None = None
        try:
            unlisten = await source.listen(dirty.set)
        except Exception as e:
            # no live listener: the timer heartbeat still pushes, just not
            # instantly, presence must never depend on the notify path
            log.warning("presence listener unavailable, heartbeat only: %s", e.__class__.__name__)
        try:
            yield
        finally:
            pump_task.cancel()
            with suppress(asyncio.CancelledError):
                await pump_task
            if unlisten is not None:
                with suppress(Exception):
                    await unlisten()
            await source.close()

    # public surface stays minimal: no docs, no openapi endpoint
    app = FastAPI(
        title="heartbeat presence proxy",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/api/presence")
    async def presence() -> PublicPresence:
        try:
            return await current()
        except Exception as e:
            # never surface database details on the public side
            log.warning("presence snapshot failed: %s", e.__class__.__name__)
            raise HTTPException(status_code=503, detail="presence temporarily unavailable") from e

    @app.websocket("/api/presence/ws")
    async def presence_ws(ws: WebSocket) -> None:
        await ws.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        subscribers.add(queue)

        async def push() -> None:
            # first paint should not wait for the next tick or notification
            with suppress(Exception):
                await ws.send_text((await current()).model_dump_json())
            while True:
                await ws.send_text(await queue.get())

        async def drain() -> None:
            # server-push protocol: the client never sends, so ignore any frame
            # it does send and end only on disconnect. receive() surfaces the
            # close that the blocked push()/queue.get() never would.
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    return

        # racing push against the disconnect lets a client close end the handler
        # instead of leaking a task that waits on the queue forever
        push_task = asyncio.create_task(push())
        recv_task = asyncio.create_task(drain())
        try:
            await asyncio.wait({push_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            subscribers.discard(queue)
            for task in (push_task, recv_task):
                task.cancel()
                with suppress(BaseException):
                    await task

    @app.get("/api/badge/{metric}.svg")
    async def badge_svg(metric: str) -> Response:
        """Embeddable flat SVG of one aggregate metric (README/site/signature).
        Same data as /api/presence; decorative, so a snapshot failure renders
        an 'unavailable' badge rather than an error the `<img>` can't show."""
        if metric not in badge.BADGE_METRICS:
            raise HTTPException(status_code=404, detail="unknown badge")
        try:
            svg = badge.render_badge(metric, await current())
        except Exception as e:
            log.warning("badge snapshot failed: %s", e.__class__.__name__)
            svg = badge.render_error(metric)
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=60"},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = ProxySettings()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
