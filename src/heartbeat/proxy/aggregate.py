"""Turn a presence snapshot into the public, device-free shape."""

from collections.abc import Sequence
from typing import Literal

from heartbeat.models import PublicPresence
from heartbeat.proxy.presence import PresenceSnapshot, SourceState

__all__ = ["activity_tier", "aggregate"]


def activity_tier(
    states: Sequence[SourceState],
    *,
    now: float,
    online: bool,
    session_timeout: int,
    pulse_window: int,
) -> Literal["active", "around", "away"]:
    """Pure session algebra (M18), timeout-closed by construction.

    An open session (latest event of a source is a start) counts as active
    for at most session_timeout: a lost stop edge ends the session there
    instead of never. A pulse counts for pulse_window. Stops never engage.
    Signals are additive: with no signal data the tailscale baseline
    decides alone.

    The age window is closed on both sides: a future event (`at > now` from
    a skewed ingest clock or a corrupt timestamp) would otherwise read as
    age <= timeout forever and pin the tier to active, defeating the
    timeout-closed guarantee. A negative age never engages.
    """

    def engaged_by(s: SourceState) -> bool:
        age = now - s.at
        if age < 0:
            return False  # future timestamp: clock skew, never trust it
        if s.kind == "start":
            return age <= session_timeout
        if s.kind == "pulse":
            return age <= pulse_window
        return False

    engaged = any(engaged_by(s) for s in states)
    if engaged:
        return "active"
    return "around" if online else "away"


def aggregate(
    snapshot: PresenceSnapshot,
    *,
    now: float,
    uptime: float,
    online_threshold: int,
    session_timeout: int,
    pulse_window: int,
) -> PublicPresence:
    """Pure: snapshot scalars in, PublicPresence out.

    When nothing has ever beaten, last_seen_relative counts from the epoch
    (so `online` is trivially false); longest_absence is maxed with the
    currently-running gap so a long offline stretch is reflected live.
    """
    last_seen_relative = max(0, int(now - (snapshot.last_seen or 0)))
    online = last_seen_relative <= online_threshold
    strong_relative = max(0, int(now - (snapshot.strong_last or 0)))
    return PublicPresence(
        online=online,
        activity=activity_tier(
            snapshot.source_states,
            now=now,
            online=online,
            session_timeout=session_timeout,
            pulse_window=pulse_window,
        ),
        last_seen=snapshot.last_seen,
        last_seen_relative=last_seen_relative,
        longest_absence=max(snapshot.longest_absence, last_seen_relative),
        total_beats=snapshot.total_beats,
        device_count=snapshot.device_count,
        total_strong_signals=snapshot.strong_total,
        last_strong_signal=snapshot.strong_last,
        last_strong_signal_relative=strong_relative,
        uptime=int(uptime),
    )
