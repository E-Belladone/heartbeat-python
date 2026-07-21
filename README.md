# heartbeat-beacon

A tiny, self-hosted **presence beacon**: it watches your own devices over
[Tailscale](https://tailscale.com/) and publishes a single, privacy-preserving
"is she around?" signal for a personal site, without ever revealing *which*
device you are on or leaking anything else.

Two pieces:

- **poller** (`heartbeat-poller`) parses `tailscale status --json`, debounces it,
  and records a "beat" per tracked device into Postgres.
- **privacy proxy** (`heartbeat-proxy`) reads an **aggregate-only** snapshot (a
  label-free SQL view, device names never enter the process), turns it into a
  small `PublicPresence` JSON, and serves it over `GET /api/presence`, a live
  websocket, and an optional embeddable SVG badge. Errors degrade to opaque
  503s; nothing about your devices leaks.

## Privacy, by construction

The proxy's SQL selects **aggregates only** (`presence.stats`, a view that never
exposes a hostname or id), its DB role is read-only, and `PublicPresence` is a
fixed, reviewed shape (online / a coarse activity tier / last-seen / counts /
uptime). No cookies, no analytics.

## Quick start

```sh
uv sync
# create the DB objects (see deploy/db/) and set the two DSNs:
cp .env.example .env   # fill in HEARTBEAT_POLLER_DSN / HEARTBEAT_PROXY_DSN
uv run heartbeat-poller   # on the machine that can run `tailscale status`
uv run heartbeat-proxy    # behind your reverse proxy (see deploy/nginx/)
```

Frontend (the public site widget) lives in `frontend/` and talks to
`/api/presence`.

## Scope

This is the **public half** of a larger personal system, extracted to be useful
on its own. The richer "activity tier" (active / around / away) is driven by
device-pushed signals in the full system; here it degrades gracefully to a
Tailscale-only baseline (online / away by last beat). Nothing private lives in
this repo.

## License

[AGPL-3.0-or-later](LICENSE). If you run a modified version as a network
service, you must offer its source to your users.
