# heartbeat

Two self-hosted pieces from one personal telemetry system, extracted to be useful
on their own:

- a **presence beacon** that watches your own devices over
  [Tailscale](https://tailscale.com/) and publishes a single privacy-preserving
  "is she around?" signal, without ever revealing *which* device you are on;
- a **pharmacokinetics model** that turns a log of intakes into a level curve,
  and calibrates that curve against real bloodwork when you have any.

They share a database and nothing else. Run either without the other.

## The presence beacon

- **poller** (`heartbeat-poller`) parses `tailscale status --json`, debounces it,
  and records a "beat" per tracked device into Postgres.
- **privacy proxy** (`heartbeat-proxy`) reads an **aggregate-only** snapshot (a
  label-free SQL view, device names never enter the process), turns it into a
  small `PublicPresence` JSON, and serves it over `GET /api/presence`, a live
  websocket, and an optional embeddable SVG badge. Errors degrade to opaque 503s.
- **ingest** (`heartbeat-ingest`) accepts device-pushed activity signals over
  per-device tokens, so the activity tier can be sharper than "did we see a
  beat". Optional: presence keeps working when every push client dies.

### Privacy, by construction

The design constraint was that a public page must never say which machine someone
is sitting at, because for some people that is a physical-safety question rather
than a preference. So it is enforced in layers that do not rely on remembering to
be careful:

- The proxy's SQL selects **aggregates only**, from views that never expose a
  hostname or an id. Device names never enter the public-facing process.
- Its database role is read-only and is granted nothing else. The grants are the
  fence, so you can check them with `\dp` rather than trusting a comment.
- `PublicPresence` is a fixed, reviewed shape: online, a coarse activity tier,
  last-seen, counts, uptime. Its field set is pinned by a test, so widening the
  public surface means editing that test on purpose.
- No cookies, no analytics, no third-party requests.

## The pharmacokinetics model

`src/heartbeat/logger/kinetics.py` is a small library of first-order absorption
families over parallel inputs:

| Family | Shape | Fits |
|---|---|---|
| `instant` | whole dose present at once, single exponential decay | idealised fast oral bolus |
| `bateman` | first-order absorption plus first-order elimination, rise then fall | anything with a real uptake ramp |
| `flip_flop` | absorption-rate-limited (the equal-rate limit) | slow depot injections |
| `dual_peak` | two inputs, the second delayed, sharing one elimination | extended-release capsules |
| `none` | no curve, log only | anything not first-order, e.g. alcohol |

Every family is first-order and therefore linear, so a dose is a lag-shifted
Bateman hump and a curve is just the superposition of them. That is what makes
`dual_peak` cheap rather than a special case.

`levels.py` turns a catalogue row into those inputs, sums them, and fits amplitude
against lab readings (`s = C / L(t)`) so a curve can read in real serum units
instead of relative ones. An intake can carry a fed/fasted flag that swaps in a
slower absorption rate, because food delays uptake without changing clearance.

Both modules are **pure**: no I/O and no clock anywhere, time is passed in. That
is why they are testable without a database.

### What it will not do for you

The curve is **blood concentration, not felt effect**. There is no effect
compartment, deliberately, even for substances with a documented plasma-to-effect
lag. Adding one means a parameter nobody can fit without data most people do not
have.

Accuracy is floored by the inputs. Guessed doses and approximate timings dominate
the difference between candidate models, so treat a drawn curve as an
illustration of a model rather than a measurement of a body. Every half-life in
`deploy/db/seed_substances.sql` is a population figure, and individual clearance
varies severalfold.

**This is not medical software.** It draws a shape from numbers you typed. Do not
dose off it.

## Quick start

```sh
uv sync

# 1. roles, once per cluster, as a superuser. Replace every 'CHANGE-ME' first.
psql "$ADMIN_DSN" -f deploy/db/roles.sql

# 2. schema, grants and the example catalogue, per database
psql "$MIGRATE_DSN" -v ON_ERROR_STOP=1 --single-transaction \
  -f deploy/db/schema.sql -f deploy/db/grants.sql -f deploy/db/seed_substances.sql

cp .env.example .env   # fill in the DSNs

uv run heartbeat-poller   # where `tailscale status` works
uv run heartbeat-proxy    # behind your reverse proxy (see deploy/nginx/)
```

The schema is additive and idempotent (`CREATE ... IF NOT EXISTS`,
`CREATE OR REPLACE`), so it is safe to re-apply on every deploy and that is how it
is meant to be used. `seed_substances.sql` only inserts while its tables are
empty, so a redeploy will not overwrite catalogue edits you made at runtime.

Frontend: a minimal demo page in `frontend/` (presence widget plus the websocket
client). Build with `cd frontend && npm install && npm run build`.

```sh
uv run pytest        # no database required
uv run ruff check .
uv run mypy
```

## The example catalogue is an example

`deploy/db/seed_substances.sql` seeds caffeine, melatonin, paracetamol,
ibuprofen, alcohol, B12 and L-theanine, with population half-lives and a citation
where one exists. Edit it into whatever you actually log.

It deliberately seeds no `dual_peak` or `flip_flop` example even though both are
supported, because the obvious examples of each are an extended-release stimulant
and an injected depot ester, and **a substance catalogue discloses a medical
history by its membership alone**, before a single dose is recorded. That is worth
knowing before you commit yours to a public repo.

If you add rows, cite what you find. A plausible-looking half-life that nobody
fitted is worse than an absent one, because the curve it draws looks exactly as
confident as a correct one.

## Scope

This is the public half of a larger personal system. The private half holds the
logging surfaces, the dashboard, wearable ingestion, and the data itself. None of
it is here, and the extraction runs one way.

Missing pieces you would need for a full logger: the intake log table, its API,
and a UI. The model reads a catalogue and a list of `(taken_at, dose_mg, fasted)`
tuples, so the seam is small and deliberately left open.

There is no `doc/` directory. The private repo's documentation describes one
specific deployment, so it would be misleading here even with the names stripped
out; this README and the comments in the code are the documentation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and patches welcome, especially
kinetics parameters with citations. Please do not send a PR adding a catalogue
entry without a source for its numbers.

## License

[AGPL-3.0-or-later](LICENSE). If you run a modified version as a network service,
you must offer its source to your users.
