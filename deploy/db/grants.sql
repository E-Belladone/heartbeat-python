-- Object privileges for heartbeat-beacon. Apply as the database owner after
-- schema.sql (and re-apply on change; all statements are idempotent):
--   psql "$OWNER_DSN" -f grants.sql

-- poller: the only writer of presence data
GRANT USAGE ON SCHEMA presence TO heartbeat_poller;
GRANT SELECT, INSERT ON presence.beats TO heartbeat_poller;
GRANT SELECT, INSERT, UPDATE ON presence.devices TO heartbeat_poller;  -- UPDATE: the upsert's DO UPDATE no-op needs it
GRANT USAGE ON ALL SEQUENCES IN SCHEMA presence TO heartbeat_poller;

-- proxy: public-facing, reads aggregates only (never device identities). The
-- whole snapshot comes through label-free views; the base tables are withheld,
-- so even a buggy query cannot select a hostname or id.
GRANT USAGE ON SCHEMA presence TO heartbeat_proxy;
GRANT SELECT ON presence.stats TO heartbeat_proxy;
REVOKE SELECT ON presence.beats, presence.devices FROM heartbeat_proxy;
-- activity tier + strong-signal stats: the unlabeled views only, never the
-- signal tables themselves
GRANT USAGE ON SCHEMA signal TO heartbeat_proxy;
GRANT SELECT ON signal.source_state, signal.strong_stats TO heartbeat_proxy;

-- ingest: the only writer of signal events; reads tokens to authenticate a
-- client, inserts events, and can read back only an event's id + timestamp
-- (never source/kind/token, so a compromised ingest can't mine the stream)
GRANT USAGE ON SCHEMA signal TO heartbeat_ingest;
GRANT SELECT ON signal.tokens TO heartbeat_ingest;
GRANT INSERT ON signal.events TO heartbeat_ingest;
GRANT SELECT (id, at) ON signal.events TO heartbeat_ingest;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA signal TO heartbeat_ingest;
