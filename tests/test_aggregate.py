from heartbeat.models import PublicPresence
from heartbeat.proxy.aggregate import activity_tier, aggregate
from heartbeat.proxy.presence import PresenceSnapshot, SourceState

NOW = 1_800_000_000.0
SESSION_TIMEOUT = 4 * 3600
PULSE_WINDOW = 1800

SNAPSHOT = PresenceSnapshot(
    last_seen=int(NOW) - 42, longest_absence=86_400, total_beats=99_999, device_count=3
)


def public(snapshot: PresenceSnapshot, *, now: float = NOW, uptime: float = 0) -> PublicPresence:
    return aggregate(
        snapshot,
        now=now,
        uptime=uptime,
        online_threshold=150,
        session_timeout=SESSION_TIMEOUT,
        pulse_window=PULSE_WINDOW,
    )


def test_aggregate_computes_the_public_shape() -> None:
    assert public(SNAPSHOT, uptime=360_000.5).model_dump() == {
        "online": True,
        "activity": "around",  # online but no signal engaged
        "last_seen": int(NOW) - 42,
        "last_seen_relative": 42,
        "longest_absence": 86_400,
        "total_beats": 99_999,
        "device_count": 3,
        "total_strong_signals": 0,
        "last_strong_signal": None,
        "last_strong_signal_relative": int(NOW),  # epoch fallback, like last_seen
        "uptime": 360_000,
    }


def test_strong_signal_stats_pass_through() -> None:
    snapshot = SNAPSHOT.model_copy(update={"strong_total": 12, "strong_last": int(NOW) - 300})
    result = public(snapshot)
    assert result.total_strong_signals == 12
    assert result.last_strong_signal == int(NOW) - 300
    assert result.last_strong_signal_relative == 300


def test_online_threshold_boundary() -> None:
    at_threshold = PresenceSnapshot(
        last_seen=int(NOW) - 150, longest_absence=0, total_beats=1, device_count=1
    )
    beyond = PresenceSnapshot(
        last_seen=int(NOW) - 151, longest_absence=0, total_beats=1, device_count=1
    )
    assert public(at_threshold).online is True
    assert public(beyond).online is False


def test_longest_absence_includes_the_running_gap() -> None:
    snapshot = PresenceSnapshot(
        last_seen=int(NOW) - 100_000, longest_absence=86_400, total_beats=1, device_count=1
    )
    assert public(snapshot).longest_absence == 100_000


def test_never_beaten() -> None:
    empty = PresenceSnapshot(last_seen=None, longest_absence=0, total_beats=0, device_count=0)
    result = public(empty)
    assert result.online is False
    assert result.activity == "away"
    assert result.last_seen is None
    assert result.last_seen_relative == int(NOW)  # epoch fallback when nothing ever beat


def tier(states: list[SourceState], *, online: bool = True) -> str:
    return activity_tier(
        states,
        now=NOW,
        online=online,
        session_timeout=SESSION_TIMEOUT,
        pulse_window=PULSE_WINDOW,
    )


def test_open_session_is_active_until_timeout() -> None:
    fresh = SourceState(kind="start", at=int(NOW) - 60)
    at_timeout = SourceState(kind="start", at=int(NOW) - SESSION_TIMEOUT)
    beyond = SourceState(kind="start", at=int(NOW) - SESSION_TIMEOUT - 1)
    assert tier([fresh]) == "active"
    assert tier([at_timeout]) == "active"
    # timeout-closed: a lost stop edge ends the session here, not never
    assert tier([beyond]) == "around"
    assert tier([beyond], online=False) == "away"


def test_pulse_engages_within_its_window() -> None:
    assert tier([SourceState(kind="pulse", at=int(NOW) - PULSE_WINDOW)]) == "active"
    assert tier([SourceState(kind="pulse", at=int(NOW) - PULSE_WINDOW - 1)]) == "around"


def test_future_timestamp_never_engages() -> None:
    # a skewed ingest clock or corrupt `at` in the future must not read as
    # age <= timeout forever and pin the tier to active (timeout-closed)
    future_start = SourceState(kind="start", at=int(NOW) + 10_000)
    future_pulse = SourceState(kind="pulse", at=int(NOW) + 10_000)
    assert tier([future_start]) == "around"
    assert tier([future_start], online=False) == "away"
    assert tier([future_pulse]) == "around"


def test_stops_never_engage() -> None:
    just_stopped = SourceState(kind="stop", at=int(NOW) - 1)
    assert tier([just_stopped]) == "around"
    assert tier([just_stopped], online=False) == "away"


def test_any_engaged_source_wins() -> None:
    states = [
        SourceState(kind="stop", at=int(NOW) - 10),  # phone locked...
        SourceState(kind="start", at=int(NOW) - 300),  # ...but the pc session is open
    ]
    assert tier(states) == "active"


def test_no_signal_data_falls_back_to_the_baseline() -> None:
    # signals are additive: an empty stream must never break presence
    assert tier([]) == "around"
    assert tier([], online=False) == "away"


def test_privacy_shape_is_pinned() -> None:
    """PublicPresence has no field that could carry a device identity.

    If this set ever grows, the addition must be reviewed against privacy
    invariant #1 first.
    """
    assert set(public(SNAPSHOT).model_dump()) == {
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
