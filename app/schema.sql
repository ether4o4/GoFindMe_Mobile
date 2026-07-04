-- GoFindMe schema. Applied idempotently on startup.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- Single-user auth (id is pinned to 1).
CREATE TABLE IF NOT EXISTS app_user (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  username   TEXT NOT NULL,
  pw_hash    TEXT NOT NULL,           -- argon2id
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT,
  updated_at TEXT
);

-- API keys. blob is either an encrypted {v,salt,iv,ct} JSON or plaintext per mode.
CREATE TABLE IF NOT EXISTS vault_secrets (
  provider   TEXT PRIMARY KEY,
  blob       TEXT NOT NULL,
  mode       TEXT NOT NULL DEFAULT 'encrypted',
  updated_at TEXT NOT NULL
);

-- A small encrypted check-blob proves the passphrase on unlock without decrypting keys.
CREATE TABLE IF NOT EXISTS vault_meta (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  check_blob TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- User-defined tools (the "add new software easily" registry).
CREATE TABLE IF NOT EXISTS custom_tools (
  name           TEXT PRIMARY KEY,
  categories     TEXT NOT NULL DEFAULT '[]',   -- JSON array
  accepts        TEXT NOT NULL DEFAULT '[]',   -- JSON array of target types
  bin            TEXT NOT NULL,
  run_template   TEXT NOT NULL,                -- e.g. "{bin} -u {target}"
  install_method TEXT NOT NULL DEFAULT 'none', -- pip|pipx|go|git|npm|none
  install_ref    TEXT,                         -- package / module@version / repo url
  version_cmd    TEXT,                         -- e.g. "{bin} --version"
  timeout_s      INTEGER NOT NULL DEFAULT 180,
  auto_runnable  INTEGER NOT NULL DEFAULT 1,
  interactive    INTEGER NOT NULL DEFAULT 0,
  notes          TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT
);

-- Personal-footprint data layer.
CREATE TABLE IF NOT EXISTS identity_items (
  id         INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL,            -- email|username|handle|realname|phone|domain
  value      TEXT NOT NULL,
  label      TEXT,
  notes      TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE (kind, value)
);

CREATE TABLE IF NOT EXISTS accounts (
  id               INTEGER PRIMARY KEY,
  service          TEXT NOT NULL,
  identity_item_id INTEGER REFERENCES identity_items(id) ON DELETE SET NULL,
  url              TEXT,
  status           TEXT,              -- active|closed|unknown
  recovery_email   TEXT,
  recovery_phone   TEXT,
  has_2fa          INTEGER,           -- 0/1/NULL
  recovery_status  TEXT,              -- configured|missing|exposed|unknown
  last_verified    TEXT,
  notes            TEXT,
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline_events (
  id          INTEGER PRIMARY KEY,
  event_type  TEXT NOT NULL,          -- account_created|device_added|breach|note
  ref_table   TEXT,
  ref_id      INTEGER,
  occurred_at TEXT,                   -- ISO date or year; may be approximate
  title       TEXT NOT NULL,
  detail      TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_nodes (
  id         INTEGER PRIMARY KEY,
  node_type  TEXT NOT NULL,           -- person|email|username|account|device
  label      TEXT NOT NULL,
  ref_table  TEXT,
  ref_id     INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges (
  id         INTEGER PRIMARY KEY,
  src_id     INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  dst_id     INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  relation   TEXT NOT NULL,           -- owns|recovers|uses|linked
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
  id         INTEGER PRIMARY KEY,
  ref_table  TEXT,
  ref_id     INTEGER,
  body       TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS logs (
  id       INTEGER PRIMARY KEY,
  ts       TEXT NOT NULL,
  level    TEXT NOT NULL,             -- info|warn|error|audit
  category TEXT,                      -- auth|tool|provider|vault|mgmt
  message  TEXT NOT NULL,
  meta     TEXT                       -- JSON
);

CREATE TABLE IF NOT EXISTS jobs (
  id          TEXT PRIMARY KEY,       -- uuid4
  parent_id   TEXT REFERENCES jobs(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,          -- tool|provider|search_all|manage
  name        TEXT NOT NULL,          -- tool/provider name or action
  target      TEXT NOT NULL,
  target_type TEXT NOT NULL,
  status      TEXT NOT NULL,          -- queued|running|done|error|timeout|cancelled
  returncode  INTEGER,
  output      TEXT,
  error       TEXT,
  created_at  TEXT NOT NULL,
  started_at  TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS findings (
  id          INTEGER PRIMARY KEY,
  job_id      TEXT REFERENCES jobs(id) ON DELETE SET NULL,
  source_kind TEXT NOT NULL,          -- tool|provider
  source_name TEXT NOT NULL,
  target      TEXT NOT NULL,
  target_type TEXT NOT NULL,
  summary     TEXT,                   -- JSON normalized summary
  raw         TEXT,                   -- JSON raw payload (capped)
  created_at  TEXT NOT NULL
);

-- ===================== v2: investigations / cases =====================
-- A search rolls up into a Case. Findings, notes and timeline can be scoped to
-- a case_id (added by migration for existing DBs; see db._migrate).
CREATE TABLE IF NOT EXISTS cases (
  id           INTEGER PRIMARY KEY,
  ref          TEXT UNIQUE,               -- human case number, e.g. GFM-2026-0007
  title        TEXT NOT NULL,
  subject      TEXT,                       -- primary target/subject value
  subject_type TEXT,                       -- username|email|domain|ip|...
  status       TEXT NOT NULL DEFAULT 'open',    -- open|active|closed|archived
  priority     TEXT NOT NULL DEFAULT 'normal',  -- low|normal|high|urgent
  examiner     TEXT,                       -- who is running the investigation
  authority    TEXT,                       -- legal authority / authorization reference
  summary      TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

-- Case file attachments (evidence uploads). The file is stored on disk under the
-- uploads dir (one folder per case) with a generated stored_name, so the client
-- filename never touches the filesystem path. Uploaded files also surface as
-- nodes on the case relationship graph.
CREATE TABLE IF NOT EXISTS case_files (
  id           INTEGER PRIMARY KEY,
  case_id      INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  filename     TEXT NOT NULL,            -- original name, sanitized for display
  stored_name  TEXT NOT NULL,            -- generated name on disk (uuid + safe ext)
  content_type TEXT,
  size         INTEGER NOT NULL DEFAULT 0,
  sha256       TEXT,
  label        TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_files_case ON case_files(case_id);

-- Tamper-evident audit trail: an append-only hash chain. Each row's hash binds
-- the previous row's hash, so any edit/deletion breaks the chain and is provable
-- via /api/audit/verify. Never store secrets in detail.
CREATE TABLE IF NOT EXISTS audit_chain (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL,
  actor      TEXT,
  action     TEXT NOT NULL,
  category   TEXT,
  detail     TEXT,                         -- JSON, never secrets
  prev_hash  TEXT NOT NULL,
  hash       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_chain(ts);

CREATE INDEX IF NOT EXISTS idx_findings_target  ON findings(target, target_type);
CREATE INDEX IF NOT EXISTS idx_jobs_parent       ON jobs(parent_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created       ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_timeline_occurred ON timeline_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_logs_ts           ON logs(ts);
