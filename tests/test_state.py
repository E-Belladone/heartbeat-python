from heartbeat.models import TailscaleDevice
from heartbeat.poller.state import PresenceTracker


def dev(hostname: str, online: bool = True) -> TailscaleDevice:
    return TailscaleDevice(hostname=hostname, online=online)


def test_not_due_before_debounce_window() -> None:
    tracker = PresenceTracker(debounce=120)
    assert tracker.update([dev("laptop")], now=0) == []
    assert tracker.update([dev("laptop")], now=60) == []


def test_due_after_sustained_online() -> None:
    tracker = PresenceTracker(debounce=120)
    tracker.update([dev("laptop")], now=0)
    assert tracker.update([dev("laptop")], now=120) == ["laptop"]
    # and on every poll after that
    assert tracker.update([dev("laptop")], now=180) == ["laptop"]


def test_offline_resets_the_streak() -> None:
    tracker = PresenceTracker(debounce=120)
    tracker.update([dev("laptop")], now=0)
    tracker.update([dev("laptop", online=False)], now=60)
    assert tracker.update([dev("laptop")], now=120) == []
    assert tracker.update([dev("laptop")], now=240) == ["laptop"]


def test_vanished_device_counts_as_offline() -> None:
    tracker = PresenceTracker(debounce=120)
    tracker.update([dev("laptop")], now=0)
    tracker.update([], now=60)  # dropped out of tailscale status entirely
    assert tracker.update([dev("laptop")], now=120) == []


def test_zero_debounce_beats_immediately() -> None:
    tracker = PresenceTracker(debounce=0)
    assert tracker.update([dev("laptop")], now=0) == ["laptop"]


def test_devices_are_tracked_independently() -> None:
    tracker = PresenceTracker(debounce=120)
    tracker.update([dev("laptop"), dev("phone", online=False)], now=0)
    tracker.update([dev("laptop"), dev("phone")], now=60)
    assert tracker.update([dev("laptop"), dev("phone")], now=120) == ["laptop"]
    assert tracker.update([dev("laptop"), dev("phone")], now=180) == ["laptop", "phone"]
