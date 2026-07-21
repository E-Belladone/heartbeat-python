from collections.abc import Sequence

from heartbeat.models import TailscaleDevice
from heartbeat.poller.main import poll_once
from heartbeat.poller.state import PresenceTracker


class FakeSink:
    def __init__(self, tracked: set[str] | None = None) -> None:
        self.tracked: set[str] = tracked or set()
        self.registered: list[str] = []
        self.beats: list[tuple[str, float]] = []
        self.fail_for: set[str] = set()

    async def sync_devices(self, devices: Sequence[TailscaleDevice], now: float) -> frozenset[str]:
        for d in devices:
            if d.hostname not in self.registered:
                self.registered.append(d.hostname)
        return frozenset(self.tracked)

    async def beat(self, hostname: str, now: float) -> None:
        if hostname in self.fail_for:
            raise ConnectionError("pg down")
        self.beats.append((hostname, now))

    async def close(self) -> None:
        pass


def status_of(*names: str) -> Sequence[TailscaleDevice]:
    return [TailscaleDevice(hostname=n, online=True) for n in names]


async def test_due_tracked_devices_get_beats() -> None:
    tracker = PresenceTracker(debounce=0)
    sink = FakeSink(tracked={"laptop", "phone"})

    async def status() -> Sequence[TailscaleDevice]:
        return status_of("laptop", "phone")

    await poll_once(tracker, sink, 1000.0, status)
    assert sink.beats == [("laptop", 1000.0), ("phone", 1000.0)]


async def test_untracked_devices_register_but_never_beat() -> None:
    tracker = PresenceTracker(debounce=0)
    sink = FakeSink(tracked={"laptop"})

    async def status() -> Sequence[TailscaleDevice]:
        return status_of("laptop", "guest-device")

    await poll_once(tracker, sink, 1000.0, status)
    # the guest self-registers (visible on the dashboard) but gets no beat
    assert sink.registered == ["laptop", "guest-device"]
    assert sink.beats == [("laptop", 1000.0)]


async def test_tracked_set_is_read_fresh_each_poll() -> None:
    tracker = PresenceTracker(debounce=0)
    sink = FakeSink(tracked=set())

    async def status() -> Sequence[TailscaleDevice]:
        return status_of("laptop")

    await poll_once(tracker, sink, 1000.0, status)
    assert sink.beats == []
    # dashboard toggles tracking on: the next poll picks it up, no restart
    sink.tracked.add("laptop")
    await poll_once(tracker, sink, 1060.0, status)
    assert sink.beats == [("laptop", 1060.0)]


async def test_one_failed_write_does_not_stop_the_cycle() -> None:
    tracker = PresenceTracker(debounce=0)
    sink = FakeSink(tracked={"laptop", "phone"})
    sink.fail_for = {"laptop"}

    async def status() -> Sequence[TailscaleDevice]:
        return status_of("laptop", "phone")

    await poll_once(tracker, sink, 1000.0, status)
    assert sink.beats == [("phone", 1000.0)]


async def test_debounce_still_gates_beats() -> None:
    tracker = PresenceTracker(debounce=120)
    sink = FakeSink(tracked={"laptop"})

    async def status() -> Sequence[TailscaleDevice]:
        return status_of("laptop")

    await poll_once(tracker, sink, 0.0, status)
    assert sink.beats == []
    await poll_once(tracker, sink, 120.0, status)
    assert sink.beats == [("laptop", 120.0)]
