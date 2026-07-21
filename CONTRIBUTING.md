# Contributing

Contributions welcome. This is the public presence-beacon half of a larger
personal system; please keep PRs scoped to the beacon (poller / proxy / the
public site). Anything about substance/mood/health tracking is deliberately
not part of this project.

## Dev loop

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

Postgres integration tests need a throwaway database; unit tests run against
in-memory doubles. Please keep the privacy invariant intact: the proxy must
never select a device name/id, and `PublicPresence` must stay aggregate-only.

By contributing you agree your work is licensed under AGPL-3.0-or-later.
