"""Poller entry point: poll tailscale status, record beats for due devices."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from heartbeat.config import PollerSettings
from heartbeat.models import TailscaleDevice
from heartbeat.poller.beat import BeatSink, PostgresBeatSink
from heartbeat.poller.state import PresenceTracker
from heartbeat.tailscale import TailscaleError, get_status

__all__ = ["main", "poll_once", "run"]

log = logging.getLogger("heartbeat.poller")

StatusFn = Callable[[], Awaitable[Sequence[TailscaleDevice]]]


async def poll_once(
    tracker: PresenceTracker,
    sink: BeatSink,
    now: float,
    status_fn: StatusFn,
) -> None:
    """One poll cycle: register seen devices, record a beat per due tracked one."""
    devices = await status_fn()
    # every seen device self-registers; which ones are *tracked* lives in the
    # database (dashboard toggle), not in config
    tracked = await sink.sync_devices(devices, now)
    for hostname in tracker.update(devices, now):
        if hostname not in tracked:
            continue
        try:
            await sink.beat(hostname, now)
            log.info("beat recorded for %s", hostname)
        except Exception:
            log.exception("beat write failed for %s", hostname)


async def run(settings: PollerSettings) -> None:
    tracker = PresenceTracker(settings.debounce)
    sink = PostgresBeatSink(settings.dsn.get_secret_value())
    await sink.connect()

    async def status() -> Sequence[TailscaleDevice]:
        return await get_status(timeout=settings.status_timeout)

    try:
        while True:
            try:
                # wall-clock time: beats are real timestamps in the database
                await poll_once(tracker, sink, time.time(), status)
            except TailscaleError:
                log.exception("tailscale status failed, retrying next poll")
            except Exception:
                # e.g. a database blip during sync_devices: keep polling
                log.exception("poll cycle failed, retrying next poll")
            await asyncio.sleep(settings.poll_interval)
    finally:
        await sink.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(run(PollerSettings()))
    except KeyboardInterrupt:
        log.info("poller stopped")
