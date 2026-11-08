"""SQLite store: the controller's only memory. Everything needed to resume after a crash lives here.

Design rule: anything that moves the world forward (ingesting a chunk, sending a proposal) is written
here first or in the same transaction, so a kill at any line leaves a state we can reconcile.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);

-- one row per chunk we have fully ingested (cursor + idempotency)
CREATE TABLE IF NOT EXISTS chunks (n INTEGER PRIMARY KEY, kind TEXT, events INTEGER, ingested_at REAL);

-- lead features, needed to slice calls by segment (call events carry lead_id, not features)
CREATE TABLE IF NOT EXISTS leads (lead_id TEXT PRIMARY KEY, seg TEXT);

-- aggregate counters. bucket = sim day (history days are negative).
-- key examples: 'all', 'welcome_message=W2', 'voice=V3|age_band=60+', 'caller_id=D1', 'prompt_version=P2'
CREATE TABLE IF NOT EXISTS agg (
  wf TEXT, day INTEGER, hour INTEGER, key TEXT,
  dials INTEGER, conn INTEGER, eng INTEGER, halluc INTEGER,
  PRIMARY KEY (wf, day, hour, key));

-- every config version we have seen (from config_changed events / API)
CREATE TABLE IF NOT EXISTS config_versions (
  wf TEXT, version INTEGER, actor TEXT, sim_minute INTEGER, changed_dims TEXT,
  proposal_id TEXT, approval_id TEXT, config TEXT, handled INTEGER DEFAULT 0, PRIMARY KEY (wf, version));

-- the shared cohort object: one id used by detection, experiments and the supervisor view
CREATE TABLE IF NOT EXISTS cohorts (
  wf TEXT, cohort_id TEXT, where_json TEXT, created_minute INTEGER, reason TEXT,
  PRIMARY KEY (wf, cohort_id));

-- experiments: one row per (wf, cohort, dim). arms is JSON {option: share}
CREATE TABLE IF NOT EXISTS experiments (
  exp_id TEXT PRIMARY KEY, wf TEXT, cohort_id TEXT, dim TEXT, metric TEXT,
  status TEXT,            -- planned | running | promoted | rolled_back | closed
  control TEXT, arms TEXT, winner TEXT, started_minute INTEGER, decided_minute INTEGER,
  start_day INTEGER, promo_day INTEGER, notes TEXT);

-- proposals: written BEFORE the HTTP call (status 'intent'), then advanced by the state machine
CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY, wf TEXT, path TEXT,  -- approval | auto
  status TEXT,   -- intent | pending | approved | applying | applied | rejected | expired | lapsed | stale | failed
  urgent INTEGER, base_version INTEGER, approval_id TEXT, applied_version INTEGER,
  created_minute INTEGER, decided_minute INTEGER, apply_by TEXT,
  summary TEXT, body TEXT, reasons TEXT, intents TEXT);

-- the audit log: every decision the controller made, with why
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sim_minute INTEGER, ts TEXT, wf TEXT, kind TEXT,
  summary TEXT, detail TEXT, proposal_id TEXT, approval_id TEXT, config_version INTEGER);

-- loop health, one row per tick
CREATE TABLE IF NOT EXISTS metrics (
  sim_minute INTEGER PRIMARY KEY, wall REAL, events INTEGER, ingest_s REAL, decide_s REAL,
  credits REAL, pending INTEGER, decisions INTEGER, rss_mb REAL);

CREATE TABLE IF NOT EXISTS validations (
  run_id TEXT PRIMARY KEY, wf TEXT, prompt TEXT, n INTEGER, pass_rate REAL, sim_minute INTEGER);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None)  # we manage transactions explicitly
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.now = 0  # current sim minute, set by the loop (used to stamp decisions)

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    # ---- meta
    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def put(self, k, v, db=None):
        (db or self.db).execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v)))

    # ---- audit
    def decide(self, wf, kind, summary, detail=None, proposal_id=None, approval_id=None, version=None, db=None):
        from .util import fmt_minute
        (db or self.db).execute(
            "INSERT INTO decisions (sim_minute, ts, wf, kind, summary, detail, proposal_id, approval_id,"
            " config_version) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.now, fmt_minute(self.now), wf, kind, summary, json.dumps(detail or {}, default=str),
             proposal_id, approval_id, version))

    def q(self, sql, *a):
        return self.db.execute(sql, a).fetchall()

    def q1(self, sql, *a):
        return self.db.execute(sql, a).fetchone()

    def metric(self, **kw):
        cols = ",".join(kw)
        self.db.execute(f"INSERT OR REPLACE INTO metrics ({cols}) VALUES ({','.join('?' * len(kw))})",
                        tuple(kw.values()))

