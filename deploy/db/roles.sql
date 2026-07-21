-- Roles for heartbeat-beacon: three least-privilege logins, created once by a
-- superuser (CREATE ROLE is cluster-wide, so run this once, not per database):
--   psql "$ADMIN_DSN" -f roles.sql
-- Replace every 'CHANGE-ME' first (openssl rand -hex 24). Object privileges are
-- NOT here; they live in grants.sql, applied against the database after schema.sql.

-- poller: the only writer of presence data
CREATE ROLE heartbeat_poller LOGIN PASSWORD 'CHANGE-ME';

-- proxy: public-facing, reads aggregates only (never device identities)
CREATE ROLE heartbeat_proxy LOGIN PASSWORD 'CHANGE-ME';

-- ingest: the only writer of signal events
CREATE ROLE heartbeat_ingest LOGIN PASSWORD 'CHANGE-ME';
