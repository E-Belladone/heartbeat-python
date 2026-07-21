"""Environment-driven settings for the poller, the privacy proxy, and the
signal ingest service.

All talk to the same Postgres, each with its own least-privilege role
(deploy/db/roles.sql); DSNs are secrets because they carry the role passwords.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["IngestSettings", "PollerSettings", "ProxySettings"]


class PollerSettings(BaseSettings):
    """Central poller configuration, read from HEARTBEAT_POLLER_* env vars."""

    model_config = SettingsConfigDict(
        env_prefix="HEARTBEAT_POLLER_", env_file=".env", extra="ignore"
    )

    dsn: SecretStr
    """Postgres DSN, heartbeat_poller role (the only beat writer)."""

    poll_interval: float = 60.0
    """Seconds between `tailscale status` polls."""

    debounce: float = 120.0
    """Seconds a device must be continuously online before its first beat."""

    status_timeout: float = 10.0
    """Timeout for the `tailscale status --json` subprocess."""


class ProxySettings(BaseSettings):
    """Privacy proxy configuration, read from HEARTBEAT_PROXY_* env vars."""

    model_config = SettingsConfigDict(
        env_prefix="HEARTBEAT_PROXY_", env_file=".env", extra="ignore"
    )

    dsn: SecretStr
    """Postgres DSN, heartbeat_proxy role (read-only aggregates)."""

    online_threshold: int = 150
    """Seconds since the last beat at or below which counts as online.

    Default assumes a 60 s poll interval: 2 missed polls + slack.
    """

    cache_ttl: float = 5.0
    """Seconds to cache the presence snapshot; the public site polls this
    endpoint, no need to hit Postgres per visitor."""

    ws_interval: float = 2.0
    """Seconds between pushes on the presence websocket. Every tick sends
    the (cached) aggregate, which doubles as the keepalive."""

    active_session_timeout: int = 45 * 60
    """Seconds an open session (latest signal of a source is a start) counts
    toward the 'active' tier. Timeout-closed: a lost stop edge ends the session
    this long after its start instead of never."""

    active_pulse_window: int = 1800
    """Seconds a pulse signal counts toward the 'active' tier."""

    host: str = "127.0.0.1"
    port: int = 8100


class IngestSettings(BaseSettings):
    """Signal ingest service, read from HEARTBEAT_INGEST_* env vars.

    Tailnet-only by deployment (never behind the public vhost); every push
    additionally needs a per-device token from signal.tokens.
    """

    model_config = SettingsConfigDict(
        env_prefix="HEARTBEAT_INGEST_", env_file=".env", extra="ignore"
    )

    dsn: SecretStr
    """Postgres DSN, heartbeat_ingest role (tokens ro, events insert-only)."""

    host: str = "127.0.0.1"
    port: int = 8102
