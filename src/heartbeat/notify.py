"""The Postgres LISTEN/NOTIFY channel that wakes the presence proxy (M5).

The poller (on a new beat) and the ingest service (on a new signal) NOTIFY
this channel so the proxy can push fresh presence to open websockets the
instant something changes, instead of only polling on a timer.

The payload is a coarse source tag ('beat' / 'signal') for logs only — never
a hostname, id, or source label (privacy invariant #1). The proxy re-derives
the aggregate through its label-free SQL on every wake-up regardless of the
payload, so nothing device-identifying travels on this channel.
"""

__all__ = ["PRESENCE_CHANNEL"]

PRESENCE_CHANNEL = "presence_changed"
