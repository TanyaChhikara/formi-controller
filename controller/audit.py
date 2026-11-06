"""Read-only views over the controller's own store (C11, C12, C14). Never touches the simulator.

  python -m controller.audit why    --db state/x.db --wf nw_renewal --at "D3 14:00"
  python -m controller.audit view   --db state/x.db [--wf ks_cancel]       # supervisor's one screen
  python -m controller.audit health --db state/x.db                        # loop health + alerts
  python -m controller.audit log    --db state/x.db --wf nw_kyc [--kind did_flagged]
"""
from __future__ import annotations

import argparse
import json
import sqlite3

from .util import DAY, fmt_minute


def parse_t(s: str) -> int:
    d, hm = s.strip().upper().lstrip("D").split()
    h, m = hm.split(":")
    return int(d) * DAY + int(h) * 60 + int(m)


def kpis(db, wf, h0, h1):
    r = db.execute("SELECT COALESCE(SUM(dials),0), COALESCE(SUM(conn),0), COALESCE(SUM(eng),0), COALESCE(SUM(halluc),0) "
                   "FROM agg WHERE wf=? AND key='all' AND day*24+hour>=? AND day*24+hour<?", (wf, h0, h1)).fetchone()
    d, c, e, h = r
    return {"dials": d, "pickup": round(c / d, 4) if d else None, "engagement": round(e / c, 4) if c else None,
            "halluc_rate": round(h / c, 4) if c else None}


def why(db, wf, at):
    t = parse_t(at)
    v = db.execute("SELECT version, actor, sim_minute, changed_dims, proposal_id, approval_id FROM config_versions "
                   "WHERE wf=? AND sim_minute<=? ORDER BY version DESC LIMIT 1", (wf, t)).fetchone()
    if not v:
        print(f"{wf}: no config change at or before {at}")
        return
    version, actor, minute, dims, pid, aid = v
    print(f"{wf} at {at} was running config v{version}, applied {fmt_minute(minute)} by {actor}; changed {dims}")
    if actor == "supervisor":
        r = db.execute("SELECT ts, summary, detail FROM decisions WHERE wf=? AND kind='supervisor_edit' AND "
                       "config_version=?", (wf, version)).fetchone()
        if r:
            print(f"  controller response ({r[0]}): {r[1]}  {r[2]}")
    elif pid:
        p = db.execute("SELECT path, created_minute, summary, body, intents, status, approval_id FROM proposals "
                       "WHERE proposal_id=?", (pid,)).fetchone()
        body = json.loads(p[3])
        print(f"  proposal {pid} ({p[0]}), created {fmt_minute(p[1])}: {p[2]}")
        print(f"  why: {body.get('rationale')}")
        if p[0] == "approval":
            print(f"  evidence: {json.dumps(body.get('evidence'))}  impact_score={body.get('impact_score')} "
                  f"affected_leads={body.get('affected_leads')}")
            for ts, kind, summ in db.execute("SELECT ts, kind, summary FROM decisions WHERE proposal_id=? ORDER BY id",
                                             (pid,)):
                print(f"    {ts}  {kind:18s} {summ}")
            print(f"  approved by: the {wf} client approver via {aid} (simulated human; the API gives no name)")
        else:
            print("  approved by: auto-apply within the workflow's signed policy (no human)")
    h = minute // 60
    print(f"  before (24h): {kpis(db, wf, h - 24, h)}")
    print(f"  after  (24h): {kpis(db, wf, h, h + 24)}")
    nxt = db.execute("SELECT version, actor, sim_minute, changed_dims FROM config_versions WHERE wf=? AND version>? "
                     "ORDER BY version LIMIT 1", (wf, version)).fetchone()
    if nxt:
        print(f"  next change: v{nxt[0]} by {nxt[1]} at {fmt_minute(nxt[2])} {nxt[3]}")
    print("  what we decided since:")
    for ts, kind, summ in db.execute("SELECT ts, kind, summary FROM decisions WHERE wf=? AND sim_minute>=? AND "
                                     "sim_minute<? AND kind NOT IN ('experiment_look') ORDER BY id LIMIT 12",
                                     (wf, minute, minute + 2 * DAY)):
        print(f"    {ts}  {kind:18s} {summ}")


def view(db, wf_filter=None):
    now = json.loads((db.execute("SELECT v FROM meta WHERE k='sim_minute'").fetchone() or ["0"])[0])
    wfs = [r[0] for r in db.execute("SELECT DISTINCT wf FROM cohorts ORDER BY wf")]
    out = {"as_of": fmt_minute(now), "workflows": {}}
    for wf in wfs:
        if wf_filter and wf != wf_filter:
            continue
        exps = []
        for exp_id, cid, dim, status, control, arms, winner in db.execute(
                "SELECT exp_id, cohort_id, dim, status, control, arms, winner FROM experiments WHERE wf=? AND status "
                "IN ('planned','running','promoted') ORDER BY exp_id", (wf,)):
            look = db.execute("SELECT v FROM meta WHERE k=?", (f"look:{exp_id}",)).fetchone()
            look = json.loads(look[0]) if look else {}
            exps.append({"id": exp_id, "cohort": cid, "dim": dim, "status": status, "control": control,
                         "winner": winner, "traffic": json.loads(arms),
                         "latest_look": {o: f"{a['s']}/{a['n']} = {a['rate']:.1%}" for o, a in
                                         look.get("arms", {}).items()}, "verdict": look.get("verdict")})
        pend = [{"proposal": p, "status": st, "summary": s, "approval": a} for p, st, s, a in db.execute(
            "SELECT proposal_id, status, summary, approval_id FROM proposals WHERE wf=? AND status IN "
            "('intent','pending','approved','applying')", (wf,))]
        today = [f"{fmt_minute(m)} v{v} by {a}: {d}" for v, a, m, d in db.execute(
            "SELECT version, actor, sim_minute, changed_dims FROM config_versions WHERE wf=? AND sim_minute>=? "
            "ORDER BY version", (wf, now - now % DAY))]
        inc = db.execute("SELECT v FROM meta WHERE k=?", (f"incident:{wf}",)).fetchone()
        bad = db.execute("SELECT v FROM meta WHERE k=?", (f"did_bad:{wf}",)).fetchone()
        out["workflows"][wf] = {
            "being_tested": [e for e in exps if e["status"] in ("planned", "running")],
            "winning_now": [e for e in exps if e["status"] == "promoted"],
            "waiting_for_you": pend,
            "changed_today": today,
            "cohorts": [{"id": c, "where": json.loads(w), "why": r} for c, w, r in
                        db.execute("SELECT cohort_id, where_json, reason FROM cohorts WHERE wf=?", (wf,))],
            "incident": json.loads(inc[0]) if inc else None,
            "quarantined_caller_ids": json.loads(bad[0]) if bad else {},
        }
    print(json.dumps(out, indent=2, default=str))


ALERT_RULES = """
PAGE (wakes someone):
  - no tick progress for 15 wall-minutes while the scenario isn't finished  → controller stuck: check sim reachability
  - an approved proposal still unapplied 90 min after approval              → will lapse: check apply errors in `log`
  - credits below the incident reserve (10) with an incident open           → fix can't be validated: top up / human fix
  - incident open > 6 sim-hours with no proposal sent                       → look at `log --kind incident_%`
DON'T PAGE (morning report):
  - routine proposal rejected or expired, a test with no winner, a caller ID quarantined and auto-rotated
"""


def health(db):
    rows = db.execute("SELECT sim_minute, wall, events, ingest_s, decide_s, credits, pending, decisions, rss_mb "
                      "FROM metrics ORDER BY sim_minute").fetchall()
    if not rows:
        print("no metrics yet")
        return
    by_day = {}
    for m, wall, ev, ing, dec, cr, pend, nd, rss in rows:
        d = by_day.setdefault(m // DAY, {"ticks": 0, "events": 0, "ingest_s": 0.0, "decide_s": 0.0, "wall0": wall,
                                         "wall1": wall, "credits_end": cr, "decisions0": nd, "rss_mb": 0})
        d["ticks"] += 1; d["events"] += ev; d["ingest_s"] += ing; d["decide_s"] += dec
        d["wall1"] = wall; d["credits_end"] = cr; d["decisions1"] = nd; d["rss_mb"] = max(d["rss_mb"], rss)
    print(f"{'day':>4} {'events':>9} {'ev/s ingest':>11} {'decide s':>9} {'wall s':>7} {'decisions':>9} "
          f"{'credits':>7} {'rss MB':>7}")
    for day, d in sorted(by_day.items()):
        print(f"{day:>4} {d['events']:>9} {d['events'] / max(d['ingest_s'], 1e-9):>11.0f} {d['decide_s']:>9.1f} "
              f"{d['wall1'] - d['wall0']:>7.0f} {d.get('decisions1', 0) - d['decisions0']:>9} "
              f"{d['credits_end']:>7.0f} {d['rss_mb']:>7.0f}")
    last = rows[-1]
    print(f"\nnow {fmt_minute(last[0])}: pending proposals={last[6]}, credits={last[5]}")
    stuck = db.execute("SELECT proposal_id, wf, apply_by FROM proposals WHERE status='approved'").fetchall()
    print("alerts firing:", stuck or "none")
    print(ALERT_RULES)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["why", "view", "health", "log"])
    ap.add_argument("--db", required=True)
    ap.add_argument("--wf")
    ap.add_argument("--at")
    ap.add_argument("--kind")
    a = ap.parse_args(argv)
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    if a.cmd == "why":
        why(db, a.wf, a.at)
    elif a.cmd == "view":
        view(db, a.wf)
    elif a.cmd == "health":
        health(db)
    else:
        q = "SELECT ts, wf, kind, summary FROM decisions WHERE 1=1"
        args = []
        if a.wf:
            q += " AND wf=?"; args.append(a.wf)
        if a.kind:
            q += " AND kind LIKE ?"; args.append(a.kind)
        for r in db.execute(q + " ORDER BY id", args):
            print(*r)


if __name__ == "__main__":
    main()
