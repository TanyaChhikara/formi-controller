"""Governance client (C9). The only code that changes a workflow's config.

Proposal state machine (stored in `proposals`):

    intent ──POST ok──▶ pending ──▶ approved ──▶ applying ──▶ applied
      │                   │  └────▶ rejected | expired          │
      │ (crash: reconcile │              └──▶ lapsed (apply window missed)
      │  by proposal_id)  └──▶ stale (base changed before apply → policies re-propose with fresh data)
      └──▶ failed (4xx at submit)

Auto path:  intent ──PUT ok──▶ applied   |  intent ──403/409──▶ failed/stale

Rules:
- The row is written as `intent` BEFORE the HTTP call, with a fresh proposal_id. After a crash we look the
  id up in the simulator (GET /approvals, GET /config/history) instead of resending blindly.
- One approval request in flight per workflow. Everything a workflow needs is batched into it.
- Requests go out only inside approver hours (and a client's stricter hours), early enough to be decided
  the same day, and within a per-workflow 24h budget that keeps one slot in reserve for incidents.
- We never resubmit an expired/rejected/stale proposal. Policies are state-driven, so they recompute the
  change against the current config and a new proposal (new id, fresh evidence) is made.
"""
from __future__ import annotations

import copy
import json
import uuid

from .client import SimError
from .store import Store
from .util import DAY, fmt_minute, ts_to_minute

AGENT_DIMS = ("welcome_message", "voice", "caller_id")
CUSTOMER_FACING = {"welcome_message", "voice", "prompt_version", "cohorts"}

# Preferences clients told us directly (stakeholder memos). Stricter than policy, so we honour them.
CLIENT_PREFS = {
    "kestrel_finance": {"max_requests_per_24h": 2, "earliest_hour": 11},
}

OPEN = ("intent", "pending", "approved", "applying")


def dist(cfg, cohort, dim):
    return (cfg["allocations"].get(cohort) or {}).get(dim) or cfg["allocations"]["default"][dim]


def changed_dims(old, new):
    ch = []
    if old.get("cohorts", []) != new.get("cohorts", []):
        ch.append("cohorts")
    keys = set(old["allocations"]) | set(new["allocations"])
    for d in AGENT_DIMS:
        if any(_norm(dist(old, k, d)) != _norm(dist(new, k, d)) for k in keys):
            ch.append(d)
    if old.get("prompt_version") != new.get("prompt_version"):
        ch.append("prompt_version")
    if old.get("schedule") != new.get("schedule"):
        ch.append("schedule")
    return ch


def _norm(d):
    s = sum(d.values()) or 1
    return {k: round(v / s, 6) for k, v in d.items() if v > 0}


def tv(a, b):
    a, b = _norm(a), _norm(b)
    return 0.5 * sum(abs(a.get(o, 0) - b.get(o, 0)) for o in set(a) | set(b))


def max_shift(old, new):
    keys = {"default"} | {c["id"] for c in old.get("cohorts", [])} | {c["id"] for c in new.get("cohorts", [])}
    return max((tv(dist(old, k, d), dist(new, k, d)) for k in keys for d in AGENT_DIMS), default=0.0)


class Governance:
    def __init__(self, store: Store, sim, wfs: dict, on_applied):
        self.s, self.sim, self.wfs = store, sim, wfs
        self.on_applied = on_applied   # callback(wf, intents, version) — must be idempotent
        self.current = {}              # wf -> {"version", "config"}, refreshed every tick

    # ------------------------------------------------------------------ helpers
    def refresh(self, wf):
        c = self.sim.get(f"/workflows/{wf}/config")
        self.current[wf] = {"version": c["version"], "config": c["config"], "actor": c["actor"]}
        self.s.db.execute("UPDATE config_versions SET config=? WHERE wf=? AND version=? AND config IS NULL",
                          (json.dumps(c["config"]), wf, c["version"]))
        return self.current[wf]

    def open_proposals(self, wf=None):
        sql = f"SELECT proposal_id, wf, path, status, intents, approval_id FROM proposals WHERE status IN {OPEN}"
        rows = self.s.q(sql)
        return [r for r in rows if wf is None or r[1] == wf]

    def open_intent_keys(self, wf):
        keys = set()
        for r in self.open_proposals(wf):
            keys |= {i["key"] for i in json.loads(r[4])}
        return keys

    def requests_last_24h(self, wf):
        return self.s.q1("SELECT COUNT(*) FROM proposals WHERE wf=? AND path='approval' AND status!='failed'"
                         " AND created_minute > ?", wf, self.s.now - DAY)[0]

    def request_limit(self, wf):
        w = self.wfs[wf]
        lim = w["governance"]["max_requests_per_24h"]
        pref = CLIENT_PREFS.get(w["tenant_id"], {})
        return min(lim, pref.get("max_requests_per_24h", lim))

    def can_request(self, wf, urgent):
        w = self.wfs[wf]
        lo, hi = w["governance"]["approver_hours"]
        lo = max(lo, CLIENT_PREFS.get(w["tenant_id"], {}).get("earliest_hour", lo))
        hour = (self.s.now % DAY) // 60
        # leave room for the approver to decide today: worst-case latency for routine, 30 min for urgent
        lat_hi = w["governance"]["approver_latency_minutes"][1]
        last_ok = hi * 60 - (30 if urgent else min(lat_hi, 240))
        if not (lo * 60 <= self.s.now % DAY < last_ok) or hour >= hi:
            return False, "outside approver hours"
        used, lim = self.requests_last_24h(wf), self.request_limit(wf)
        budget = lim if urgent else max(lim - 1, 1)  # keep one slot for incidents
        if used >= budget:
            return False, f"24h request budget used ({used}/{lim})"
        inflight = [r for r in self.open_proposals(wf) if r[2] == "approval"]
        if inflight and not urgent:
            return False, "an approval is already in flight for this workflow"
        if urgent and any(self.s.q1("SELECT urgent FROM proposals WHERE proposal_id=?", r[0])[0] for r in inflight):
            return False, "an urgent approval is already in flight"
        return True, ""

    def auto_allowed(self, wf, old, new):
        pol = self.wfs[wf]["governance"]["auto_apply"]
        if not pol.get("enabled"):
            return False
        dims = changed_dims(old, new)
        if not dims or any(d not in pol.get("allowed_dims", []) for d in dims):
            return False
        if any(d in CUSTOMER_FACING for d in dims):   # voluntary: customers' experience changes need a human
            return False
        return max_shift(old, new) <= pol.get("max_shift", 0) + 1e-9

    # ------------------------------------------------------------------ submit
    def submit_auto(self, wf, new_cfg, intents, rationale, evidence=None):
        cur = self.current[wf]
        pid = f"auto-{wf}-{uuid.uuid4().hex[:10]}"
        body = {"proposal_id": pid, "base_version": cur["version"], "proposed_config": new_cfg,
                "rationale": rationale, "evidence": evidence or {}}
        with self.s.tx() as db:
            db.execute("INSERT INTO proposals (proposal_id, wf, path, status, urgent, base_version, created_minute,"
                       " summary, body, intents) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (pid, wf, "auto", "intent", 1, cur["version"], self.s.now, rationale,
                        json.dumps(body), json.dumps(intents)))
        try:
            r = self.sim.put(f"/workflows/{wf}/config", body)
        except SimError as e:
            st = "stale" if e.code == "stale_base_version" else "failed"
            if e.code == "duplicate_proposal_id":
                return self._reconcile_auto(pid, wf)
            with self.s.tx() as db:
                db.execute("UPDATE proposals SET status=?, reasons=? WHERE proposal_id=?",
                           (st, json.dumps(e.body), pid))
                self.s.decide(wf, "auto_apply_refused", f"auto-apply refused ({e.code})", e.body, pid, db=db)
            return None
        self._mark_applied(pid, wf, r["version"], intents)
        return r["version"]

    def submit_approval(self, wf, new_cfg, intents, urgent, payload):
        """payload: change_summary, diff, affected_leads, dry_run, impact_score, rationale, evidence."""
        cur = self.current[wf]
        pid = f"prop-{wf}-{uuid.uuid4().hex[:10]}"
        ttl = self.wfs[wf]["governance"]["proposal_ttl_hours"]
        body = {"proposal_id": pid, "workflow_id": wf, "base_version": cur["version"],
                "proposed_config": new_cfg, "expires_in_hours": ttl, **payload}
        with self.s.tx() as db:
            db.execute("INSERT INTO proposals (proposal_id, wf, path, status, urgent, base_version, created_minute,"
                       " summary, body, intents) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (pid, wf, "approval", "intent", int(urgent), cur["version"], self.s.now,
                        payload["change_summary"], json.dumps(body, default=str), json.dumps(intents)))
        try:
            r = self.sim.post("/approvals", body)
        except SimError as e:
            if e.code == "duplicate_proposal_id":
                return self._reconcile_intent(pid, wf)
            st = "stale" if e.code == "stale_base_version" else "failed"
            with self.s.tx() as db:
                db.execute("UPDATE proposals SET status=?, reasons=? WHERE proposal_id=?",
                           (st, json.dumps(e.body), pid))
                self.s.decide(wf, "proposal_refused", f"submit refused ({e.code})", e.body, pid, db=db)
            return None
        with self.s.tx() as db:
            db.execute("UPDATE proposals SET status='pending', approval_id=? WHERE proposal_id=?",
                       (r["approval_id"], pid))
            self.s.decide(wf, "proposal_sent", payload["change_summary"],
                          {"intents": [i["key"] for i in intents], "impact_score": payload["impact_score"],
                           "affected_leads": payload["affected_leads"], "urgent": urgent,
                           "expires_at": r.get("expires_at")}, pid, r["approval_id"], db=db)
        return r["approval_id"]

    def _mark_applied(self, pid, wf, version, intents, approval_id=None):
        with self.s.tx() as db:
            db.execute("UPDATE proposals SET status='applied', applied_version=?, decided_minute=? "
                       "WHERE proposal_id=?", (version, self.s.now, pid))
            self.s.decide(wf, "applied", f"config v{version} applied ({'approval' if approval_id else 'auto'})",
                          {"intents": [i["key"] for i in intents]}, pid, approval_id, version, db=db)
            self.on_applied(wf, intents, version, db)

    # ------------------------------------------------------------------ reconcile + tick
    def _reconcile_intent(self, pid, wf):
        """An approval intent whose POST outcome we don't know (crash, or duplicate id)."""
        found = [a for a in self.sim.get("/approvals", workflow_id=wf) if a["proposal_id"] == pid]
        with self.s.tx() as db:
            if found:
                db.execute("UPDATE proposals SET status='pending', approval_id=? WHERE proposal_id=?",
                           (found[0]["approval_id"], pid))
                self.s.decide(wf, "reconciled", "found in-flight approval after restart", {},
                              pid, found[0]["approval_id"], db=db)
                return found[0]["approval_id"]
            # never reached the simulator: drop it, policies will re-propose with fresh data
            db.execute("UPDATE proposals SET status='failed', reasons='\"never sent (crash)\"' "
                       "WHERE proposal_id=?", (pid,))
        return None

    def _reconcile_auto(self, pid, wf):
        hist = self.sim.get(f"/workflows/{wf}/config/history")
        hit = [h for h in hist if h.get("proposal_id") == pid]
        row = self.s.q1("SELECT intents FROM proposals WHERE proposal_id=?", pid)
        if hit:
            self._mark_applied(pid, wf, hit[0]["version"], json.loads(row[0]))
            return hit[0]["version"]
        with self.s.tx() as db:
            db.execute("UPDATE proposals SET status='failed', reasons='\"never sent (crash)\"' "
                       "WHERE proposal_id=?", (pid,))
        return None

    def reconcile_and_apply(self):
        """Every tick (and on startup): advance every open proposal using the simulator as the source of truth."""
        for pid, wf, path, status, intents_json, aid in self.open_proposals():
            intents = json.loads(intents_json)
            if status == "intent":
                if path == "auto":
                    self._reconcile_auto(pid, wf)
                else:
                    self._reconcile_intent(pid, wf)
                continue
            a = self.sim.get(f"/approvals/{aid}")
            st = a["status"]
            if st == "pending":
                continue
            if st == "applied":  # we crashed between apply and commit
                hist = self.sim.get(f"/workflows/{wf}/config/history")
                v = next(h["version"] for h in hist if h.get("approval_id") == aid)
                self._mark_applied(pid, wf, v, intents, aid)
                continue
            if st in ("rejected", "expired", "lapsed"):
                with self.s.tx() as db:
                    db.execute("UPDATE proposals SET status=?, reasons=?, decided_minute=? WHERE proposal_id=?",
                               (st, json.dumps(a.get("reasons", [])), self.s.now, pid))
                    self.s.decide(wf, f"approval_{st}", f"{aid} {st}", {"reasons": a.get("reasons", [])},
                                  pid, aid, db=db)
                continue
            if st == "approved":
                if status == "pending":
                    with self.s.tx() as db:
                        db.execute("UPDATE proposals SET status='approved', apply_by=? WHERE proposal_id=?",
                                   (a.get("apply_by"), pid))
                        self.s.decide(wf, "approval_approved", f"{aid} approved", {"decided_at": a.get("decided_at")},
                                      pid, aid, db=db)
                self._apply(pid, wf, aid, intents)

    def _apply(self, pid, wf, aid, intents):
        cur = self.refresh(wf)
        base = self.s.q1("SELECT base_version FROM proposals WHERE proposal_id=?", pid)[0]
        if cur["version"] != base:
            # someone (a supervisor, or our own auto-apply) changed the config after we proposed. Don't force
            # it: mark stale; policies recompute against the new config and re-propose with fresh evidence.
            with self.s.tx() as db:
                db.execute("UPDATE proposals SET status='stale' WHERE proposal_id=?", (pid,))
                self.s.decide(wf, "approval_stale", f"{aid} approved but base v{base} != current "
                              f"v{cur['version']}; not applied, will re-propose", {}, pid, aid, db=db)
            return
        with self.s.tx() as db:
            db.execute("UPDATE proposals SET status='applying' WHERE proposal_id=?", (pid,))
        try:
            r = self.sim.post(f"/workflows/{wf}/apply", {"approval_id": aid})
        except SimError as e:
            st = {"stale_base_version": "stale", "approval_lapsed": "lapsed"}.get(e.code, "failed")
            if e.code == "not_approved" and e.body.get("detail", {}).get("status") == "applied":
                return self.reconcile_and_apply()
            with self.s.tx() as db:
                db.execute("UPDATE proposals SET status=?, reasons=? WHERE proposal_id=?",
                           (st, json.dumps(e.body), pid))
                self.s.decide(wf, f"apply_{st}", f"apply of {aid} failed ({e.code})", e.body, pid, aid, db=db)
            return
        self._mark_applied(pid, wf, r["version"], intents, aid)
