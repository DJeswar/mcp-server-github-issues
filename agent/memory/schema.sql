-- Long-term memory. Verified against SQLite 3.50.4.
--
-- Liveness gates on `active`, NOT on `superseded_by IS NULL`. That is not a style choice: a
-- partial unique index on `superseded_by IS NULL` cannot perform a supersede at all. Insert the
-- new row first and the old row is still live, so UNIQUE fails; retire the old row first and it
-- needs the new row's id, which does not exist yet, so FOREIGN KEY fails. Worse, with
-- foreign_keys OFF (SQLite's default) that second case is accepted silently and leaves a
-- dangling reference.

CREATE TABLE IF NOT EXISTS facts (
  id            INTEGER PRIMARY KEY,
  key           TEXT NOT NULL,        -- '<namespace>.<attribute>', e.g. 'priority.milestone'
  value         TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('preference','decision','mapping','constraint')),
  scope         TEXT NOT NULL,        -- 'global' or 'repo:owner/name'

  -- Rule 3 (user-asserted) made structural. 'tool_result' is not an accepted value, so a
  -- careless future caller gets an IntegrityError instead of a silent memory-poisoning
  -- regression. Verified: SQLite rejects the insert, not our Python.
  source        TEXT NOT NULL CHECK (source IN ('user_asserted','user_confirmed')),
  source_quote  TEXT NOT NULL,
  session_id    TEXT NOT NULL,

  created_at    TEXT NOT NULL,
  last_used_at  TEXT,
  use_count     INTEGER NOT NULL DEFAULT 0,
  confidence    REAL NOT NULL DEFAULT 1.0,
  expires_at    TEXT,

  active        INTEGER NOT NULL DEFAULT 1,
  superseded_by INTEGER REFERENCES facts(id)
);

-- At most one live value per (key, scope). Memory cannot hold two contradictory answers to the
-- same question; a new assertion supersedes the old one and the old row stays for audit.
CREATE UNIQUE INDEX IF NOT EXISTS facts_live ON facts(key, scope) WHERE active = 1;

CREATE INDEX IF NOT EXISTS facts_scope ON facts(scope, active);

-- Guardrail firings. A table rather than only log lines because the README's headline number
-- ("N injection attempts blocked") and the Phase 5 per-category pass rate both need to COUNT
-- these, and counting a log file is not a measurement.
--
-- `direction` is about the agent's boundary: inbound = data entering it (tool results),
-- outbound = anything leaving it (an answer, or a tool call it tried to make).
CREATE TABLE IF NOT EXISTS guardrail_events (
  id         INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  detector   TEXT NOT NULL,
  direction  TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  source     TEXT NOT NULL,
  action     TEXT NOT NULL,
  span_start INTEGER,
  span_end   INTEGER,
  detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS guardrail_events_detector
  ON guardrail_events(detector, direction);
