"""The learning loop. Policies are STATE-DRIVEN: every tick they look at the store + current config and say
what change they want ("intents"). Governance decides if and how it can be sent. Because nothing depends on
remembering an in-memory event, a restart simply recomputes the same intents.

Policies
  1. supervisor edits   — respected, never undone silently; experiments on the edited dim are closed
  2. hallucination (C8) — detect on a population → cheapest credible fix (revert to last known-good prompt,
                          LLM only if none) → validate → urgent proposal with evidence → verify after apply
  3. caller-ID (C5)     — a DID whose pickup collapses vs its peers is quarantined; auto-apply where allowed
  4. experiments (C6/7) — welcome/voice for engagement-primary, caller_id for pickup-primary; Holm-corrected
                          tests, one look per day, promote with a holdout, watch for decay, roll back
"""
from __future__ import annotations

import copy
import json
import math
import re

from .governance import CLIENT_PREFS, changed_dims, dist, max_shift, tv
from .stats import binom_excess_z, holm, norm_sf, poisson_sf, two_prop_z, wilson
from .util import DAY, fmt_minute

FEATURES = ("lang", "city_tier", "age_band", "value_band")

# ---- tunables (see SUBMISSION.md §5 for the reasoning behind each)
EXPLORE_TOTAL = 0.30      # share of a dim's traffic given to challengers while exploring
HOLDOUT = 0.15            # share kept on the old control after promotion: the drift-proof yardstick for decay
N_MIN = {"engagement_rate": 400, "pickup_rate": 1200}   # per-arm sample before any look
ALPHA_LOOK = 0.015        # one-sided per daily look, Holm across arms; ≈ Pocock nominal level for 5 looks
MAX_COHORTS = 4           # cohorts we create per workflow (sim allows 20); more fragments traffic
SEG_MIN = 200             # per-arm connected calls inside a segment before it can be tested
DECAY_WINDOW_H = 24
COOLDOWN_MIN = DAY        # after close/rollback/supervisor edit, wait before re-experimenting on a dim
RETIRE_MIN = 7 * DAY      # a losing option is not re-tested for a week
HALLUC = {"window_h": 6, "min_conn": 120, "mult": 3.0, "p": 1e-7, "p_after_change": 1e-4, "z": 4.0}
RECENT_H = 48             # window for catching arms that faded after looking fine
DID_MAX_SHARE = 0.6       # never concentrate dialling on one number: volume drives spam flags
DID = {"window_h": 3, "min_dials": 120, "z": -3.5, "ratio": 0.7}
CREDIT_FLOOR = 10         # never spend below this (reserve for the next incident)
INCIDENT_CREDIT_CAP = 15
VALIDATION_N = 300


def metric_of(wf):
    return wf["objective"]["primary"]


def guard_of(wf):
    return "pickup_rate" if metric_of(wf) == "engagement_rate" else "engagement_rate"


def sn(row, metric):
    """(successes, trials) for a KPI from (dials, conn, eng, halluc)."""
    d, c, e, _ = row
    return (e, c) if metric == "engagement_rate" else (c, d)


def rate(s, n):
    return s / n if n else 0.0


class Brain:
    def __init__(self, store, sim, wfs, gov):
        self.s, self.sim, self.wfs, self.gov = store, sim, wfs, gov
        gov.on_applied = self.on_applied

    # ------------------------------------------------------------------ data access
    def sums(self, wf, key, h_from=None, h_to=None):
        sql = "SELECT COALESCE(SUM(dials),0), COALESCE(SUM(conn),0), COALESCE(SUM(eng),0), COALESCE(SUM(halluc),0)" \
              " FROM agg WHERE wf=? AND key=?"
        args = [wf, key]
        if h_from is not None:
            sql += " AND day*24+hour >= ?"
            args.append(h_from)
        if h_to is not None:
            sql += " AND day*24+hour < ?"
            args.append(h_to)
        return tuple(self.s.q1(sql, *args))

    def now_h(self):
        return self.s.now // 60

    # ------------------------------------------------------------------ bootstrap (C3)
    def bootstrap(self):
        """Baselines from pre-D0 history. History ran on the default config only, so it tells us normal levels
        (hallucination rate, per-DID pickup, KPI levels) but nothing about untested variants."""
        for wf, w in self.wfs.items():
            if self.s.get(f"baseline:{wf}"):
                continue
            allr = self.sums(wf, "all", None, 0)
            base = {"pickup": rate(allr[1], allr[0]), "engage": rate(allr[2], allr[1]),
                    "halluc": rate(allr[3], allr[1]), "conn_per_day": allr[1] / max(1, self._hist_days(wf)),
                    "dials_per_day": allr[0] / max(1, self._hist_days(wf)), "did": {}}
            for d in w["options"]["caller_id"]:
                r = self.sums(wf, f"caller_id={d}", None, 0)
                if r[0]:
                    base["did"][d] = {"pickup": rate(r[1], r[0]), "dials": r[0]}
            with self.s.tx() as db:
                self.s.put(f"baseline:{wf}", base, db)
                db.execute("INSERT OR IGNORE INTO cohorts VALUES (?,?,?,?,?)",
                           (wf, "default", "{}", self.s.now, "everyone not in a more specific cohort"))
                self.s.decide(wf, "bootstrap", "baselines from history", base, db=db)

    def _hist_days(self, wf):
        r = self.s.q1("SELECT COUNT(DISTINCT day) FROM agg WHERE wf=? AND key='all' AND day<0", wf)
        return r[0] or 1

    # ------------------------------------------------------------------ main tick
    def tick(self, credits):
        self.credits = credits
        for wf in self.wfs:
            self.gov.refresh(wf)
            self.handle_config_events(wf)
        self.gov.reconcile_and_apply()
        for wf, w in self.wfs.items():
            cur = self.gov.refresh(wf)
            intents = []
            intents += self.hallucination(wf, w, cur)
            intents += self.caller_id_health(wf, w, cur)
            if self.s.now >= 0:
                busy = {d for i in intents for dd in (i.get("alloc") or {}).values() for d in dd}
                intents += self.experiments(wf, w, cur, busy_dims=busy)
            self.plan(wf, w, cur, intents)

    # ------------------------------------------------------------------ 1. supervisor edits
    def handle_config_events(self, wf):
        rows = self.s.q("SELECT version, actor, changed_dims, sim_minute FROM config_versions "
                        "WHERE wf=? AND handled=0 ORDER BY version", wf)
        for version, actor, dims_json, minute in rows:
            dims = json.loads(dims_json or "[]")
            with self.s.tx() as db:
                if actor == "supervisor":
                    closed = []
                    for exp_id, dim in db.execute("SELECT exp_id, dim FROM experiments WHERE wf=? AND status IN "
                                                  "('planned','running','promoted')", (wf,)).fetchall():
                        if dim in dims:
                            db.execute("UPDATE experiments SET status='closed', decided_minute=?, notes=? "
                                       "WHERE exp_id=?", (self.s.now, "supervisor edited this dimension", exp_id))
                            closed.append(exp_id)
                    self.s.decide(wf, "supervisor_edit",
                                  f"supervisor changed {dims} (v{version}); respected, not reverted",
                                  {"closed_experiments": closed, "at": fmt_minute(minute)}, version=version, db=db)
                    if "prompt_version" in dims:
                        self.s.put(f"prompt_watch:{wf}", {"since": minute, "version": version}, db)
                db.execute("UPDATE config_versions SET handled=1 WHERE wf=? AND version=?", (wf, version))

    # ------------------------------------------------------------------ 2. hallucination (C8)
    def hallucination(self, wf, w, cur):
        base = self.s.get(f"baseline:{wf}")
        p0 = max(base["halluc"], 0.002)
        prompt = cur["config"]["prompt_version"]
        inc = self.s.get(f"incident:{wf}")
        hf = self.now_h() - HALLUC["window_h"]
        # only count calls since this prompt went live (latest version that set it)
        since = self._prompt_since_h(wf, prompt)
        r = self.sums(wf, f"prompt_version={prompt}", max(hf, since))
        conn, hal = r[1], r[3]
        z = binom_excess_z(hal, conn, p0)
        pval = poisson_sf(hal, conn * p0)
        # a recent prompt change is a strong prior that something changed, so the bar is lower right after one;
        # otherwise ~1500 overlapping checks per run need a very small p to keep false alarms rare
        recent_change = self.now_h() - since <= 12
        bar = HALLUC["p_after_change"] if recent_change else HALLUC["p"]
        bad = conn >= HALLUC["min_conn"] and rate(hal, conn) >= HALLUC["mult"] * p0 and pval <= bar

        if inc and inc["state"] in ("resolved", "abandoned") and inc["bad_prompt"] != prompt:
            inc = None
        if inc is None:
            if not bad:
                return []
            inc = {"id": f"inc-{wf}-{self.s.now}", "bad_prompt": prompt, "opened": self.s.now, "state": "open",
                   "tried": [], "validated": {}, "credits": 0, "detect": {"conn": conn, "halluc": hal,
                   "rate": round(rate(hal, conn), 4), "baseline": round(p0, 4), "z": round(z, 1), "p": pval,
                   "after_prompt_change": recent_change}}
            self._save_inc(wf, inc, "incident_opened",
                           f"hallucination {rate(hal, conn):.1%} on {prompt} vs baseline {p0:.1%} "
                           f"({hal}/{conn} connected, p={pval:.1e})")
        if inc["state"] == "verifying":
            return self._verify_fix(wf, inc, prompt)
        if inc["state"] in ("resolved", "abandoned"):
            return []
        if prompt != inc["bad_prompt"]:   # someone else fixed it (e.g. the supervisor)
            inc["state"] = "resolved"
            self._save_inc(wf, inc, "incident_resolved", f"prompt changed to {prompt} by someone else")
            return []
        cand = self._fix_candidate(wf, w, inc)
        if cand is None:
            return []
        run = inc["validated"].get(cand)
        if run is None:
            return []
        p0e = base["engage"]
        return [{
            "key": f"prompt_fix:{inc['id']}:{cand}", "kind": "prompt_fix", "urgent": True, "operational": False,
            "prompt": cand, "alloc": {}, "incident": inc["id"],
            "summary": f"Fix hallucination incident: switch prompt {prompt} → {cand}",
            "rationale": (f"Hallucination flags on {prompt} are {inc['detect']['rate']:.1%} of connected calls vs a "
                          f"{p0:.1%} baseline (z={inc['detect']['z']}, n={inc['detect']['conn']}). {cand} passed "
                          f"validation at {run['pass_rate']:.1%} (n={run['n']}). We will check engagement after "
                          f"the switch, since validation measures safety only."),
            "evidence": {"validation_run_id": run["run_id"]},
            "impact": min(1.0, max(0.1, (inc["detect"]["rate"] - p0) / 0.02)),
            "dry_run": {"bad_prompt": prompt, "observed_halluc": inc["detect"], "candidate": cand,
                        "candidate_history": self._prompt_record(wf, cand), "baseline_engagement": round(p0e, 4),
                        "validation": run},
        }]

    def _prompt_since_h(self, wf, prompt):
        # when did the live prompt start? = the latest version that changed prompt_version
        r = self.s.q1("SELECT MAX(sim_minute) FROM config_versions WHERE wf=? AND changed_dims LIKE '%prompt_version%'", wf)
        return (r[0] // 60) if r and r[0] is not None else -10**6

    def _prompt_record(self, wf, p):
        r = self.sums(wf, f"prompt_version={p}")
        return {"conn": r[1], "halluc_rate": round(rate(r[3], r[1]), 4), "engagement": round(rate(r[2], r[1]), 4)}

    def _fix_candidate(self, wf, w, inc):
        """Cheapest credible fix first: a prompt we've actually run with a normal hallucination rate. The LLM is
        only asked when we have no such prompt. Each candidate is validated once."""
        base = self.s.get(f"baseline:{wf}")
        p0 = max(base["halluc"], 0.002)
        known = []
        for p in w["options"]["prompt_version"]:
            if p == inc["bad_prompt"] or p in inc["tried"]:
                continue
            rec = self._prompt_record(wf, p)
            if rec["conn"] >= 1000 and rec["halluc_rate"] <= 1.5 * p0:
                known.append((rec["conn"], p))
        cands = [p for _, p in sorted(known, reverse=True)]
        if not cands and not inc.get("llm"):
            if not self._can_spend(inc, 3):
                return None
            try:
                r = self.sim.post("/llm/suggest-fixes", {"workflow_id": wf, "problem":
                                  f"hallucination rate {inc['detect']['rate']:.1%} on prompt {inc['bad_prompt']}"})
            except Exception as e:  # noqa: BLE001
                self._save_inc(wf, inc, "llm_failed", str(e))
                return None
            inc["credits"] += 3
            self.credits -= 3
            inc["llm"] = [s["prompt_version"] for s in r["suggestions"]]
            self._save_inc(wf, inc, "llm_suggested", f"LLM suggested {inc['llm']}", r)
        if not cands:
            cands = [p for p in inc.get("llm", []) if p not in inc["tried"] and p != inc["bad_prompt"]]
        for p in cands:
            if p in inc["validated"]:
                return p
            cost = math.ceil(VALIDATION_N / 100)
            if not self._can_spend(inc, cost):
                return None
            gov = w["governance"]
            try:
                run = self.sim.post("/validation/runs", {"workflow_id": wf, "prompt_version": p, "n": VALIDATION_N})
            except Exception as e:  # noqa: BLE001
                self._save_inc(wf, inc, "validation_failed", str(e))
                return None
            inc["credits"] += cost
            self.credits -= cost
            with self.s.tx() as db:
                db.execute("INSERT OR REPLACE INTO validations VALUES (?,?,?,?,?,?)",
                           (run["validation_run_id"], wf, p, run["n"], run["pass_rate"], self.s.now))
            ok = run["pass_rate"] >= gov.get("min_validation_pass_rate", 0.97)
            if ok:
                inc["validated"][p] = {"run_id": run["validation_run_id"], "pass_rate": run["pass_rate"], "n": run["n"]}
                self._save_inc(wf, inc, "validation_passed", f"{p} passed validation {run['pass_rate']:.1%}", run)
                return p
            inc["tried"].append(p)
            self._save_inc(wf, inc, "validation_rejected", f"{p} failed validation {run['pass_rate']:.1%}", run)
        if not cands or all(p in inc["tried"] for p in cands):
            if inc.get("llm") is not None and all(p in inc["tried"] for p in inc["llm"]):
                inc["state"] = "abandoned"
                self._save_inc(wf, inc, "incident_escalate", "no candidate passed validation; needs a human")
        return None

    def _can_spend(self, inc, c):
        return self.credits - c >= CREDIT_FLOOR and inc["credits"] + c <= INCIDENT_CREDIT_CAP

    def _verify_fix(self, wf, inc, prompt):
        since = inc.get("fixed_h", self.now_h())
        r = self.sums(wf, f"prompt_version={prompt}", since)
        if r[1] < 200:
            return []
        base = self.s.get(f"baseline:{wf}")
        hz = binom_excess_z(r[3], r[1], max(base["halluc"], 0.002))
        ez = two_prop_z(r[2], r[1], base["engage"] * 10000, 10000)
        inc["verify"] = {"conn": r[1], "halluc_rate": round(rate(r[3], r[1]), 4),
                         "engagement": round(rate(r[2], r[1]), 4), "baseline_engagement": round(base["engage"], 4),
                         "halluc_z": round(hz, 1), "engage_z": round(ez, 1)}
        inc["state"] = "resolved"
        note = "fix verified" if hz < HALLUC["z"] and ez > -3 else "fix applied but metrics still off — needs a human"
        self._save_inc(wf, inc, "incident_verified", note, inc["verify"])
        return []

    def _save_inc(self, wf, inc, kind, summary, detail=None):
        with self.s.tx() as db:
            self.s.put(f"incident:{wf}", inc, db)
            self.s.decide(wf, kind, summary, detail or {"incident": inc["id"]}, db=db)

    # ------------------------------------------------------------------ 3. caller-ID health (C5)
    def caller_id_health(self, wf, w, cur):
        bad = self.s.get(f"did_bad:{wf}", {})
        h0 = self.now_h() - DID["window_h"]
        in_use = sorted({o for k in cur["config"]["allocations"] for o in dist(cur["config"], k, "caller_id")})
        stats = {d: self.sums(wf, f"caller_id={d}", h0) for d in w["options"]["caller_id"]}
        base = self.s.get(f"baseline:{wf}")
        newly = {}
        for d in in_use:
            if d in bad:
                continue
            dd, dc = stats[d][0], stats[d][1]
            if dd < DID["min_dials"]:
                continue
            od = sum(stats[o][0] for o in in_use if o != d and o not in bad)
            oc = sum(stats[o][1] for o in in_use if o != d and o not in bad)
            if od >= DID["min_dials"]:
                z = two_prop_z(dc, dd, oc, od)
                flag = z <= DID["z"] and rate(dc, dd) < DID["ratio"] * rate(oc, od)
                ref = rate(oc, od)
            else:   # only DID in use: compare to its own history
                ref = base["did"].get(d, {}).get("pickup") or base["pickup"]
                z = two_prop_z(dc, dd, ref * 5000, 5000)
                flag = z <= DID["z"] and rate(dc, dd) < DID["ratio"] * ref
            if flag:
                newly[d] = {"minute": self.s.now, "pickup": round(rate(dc, dd), 4), "ref": round(ref, 4),
                            "z": round(z, 1), "dials": dd}
        if newly:
            bad.update(newly)
            with self.s.tx() as db:
                self.s.put(f"did_bad:{wf}", bad, db)
                for d, info in newly.items():
                    self.s.decide(wf, "did_flagged", f"caller ID {d} pickup {info['pickup']:.1%} vs {info['ref']:.1%}"
                                  f" (z={info['z']}, {info['dials']} dials in {DID['window_h']}h): quarantined", info, db=db)
        if not any(d in bad for d in in_use):
            return []
        new = copy.deepcopy(cur["config"])
        for k, dims in new["allocations"].items():
            if "caller_id" not in dims:
                continue
            dd = {o: v for o, v in dims["caller_id"].items() if o not in bad}
            if not dd:
                spare = [o for o in w["options"]["caller_id"] if o not in bad]
                if not spare:
                    return []
                # prefer DIDs with a healthy record in our own data, then untested ones
                spare.sort(key=lambda o: -(base["did"].get(o, {}).get("pickup") or 0))
                dd = {spare[0]: 1.0}
            s = sum(dd.values())
            dims["caller_id"] = {o: v / s for o, v in dd.items()}
        bad_in_use = sorted(d for d in in_use if d in bad)
        return [{
            "key": f"did_fix:{','.join(bad_in_use)}", "kind": "did_fix", "urgent": True, "operational": True,
            "alloc": {k: {"caller_id": v["caller_id"]} for k, v in new["allocations"].items() if "caller_id" in v},
            "summary": f"Stop dialling from flagged caller ID(s) {bad_in_use}",
            "rationale": "; ".join(f"{d}: pickup {bad[d]['pickup']:.1%} vs {bad[d]['ref']:.1%} on peers "
                                   f"(z={bad[d]['z']})" for d in bad_in_use),
            "evidence": {d: bad[d] for d in bad_in_use},
            "impact": min(1.0, max(0.1, sum((bad[d]["ref"] - bad[d]["pickup"]) / max(bad[d]["ref"], 1e-6)
                                           for d in bad_in_use))),
            "dry_run": {"window_stats": {d: {"dials": stats[d][0], "conn": stats[d][1]} for d in in_use},
                        "history_baseline": base["did"]},
        }]

    # ------------------------------------------------------------------ 4. experiments (C6/C7)
    def exp_dims(self, w):
        if metric_of(w) == "engagement_rate":
            dims = ["welcome_message", "voice"]
        else:
            dims = ["caller_id"]
        return [d for d in dims if len(w["options"][d]) > 1]

    def experiments(self, wf, w, cur, busy_dims):
        out = []
        for dim in self.exp_dims(w):
            if dim in busy_dims:
                continue
            row = self.s.q1("SELECT exp_id, status, control, arms, winner, started_minute, notes, decided_minute "
                            "FROM experiments WHERE wf=? AND dim=? AND cohort_id='default' ORDER BY rowid DESC LIMIT 1",
                            wf, dim)
            if row is None or row[1] in ("closed", "rolled_back"):
                if row is not None and self.s.now - (row[7] or 0) < COOLDOWN_MIN:
                    continue
                self._plan_experiment(wf, w, cur, dim)
                continue
            exp_id, status, control, arms, winner, started, notes, _ = row
            arms = json.loads(arms)
            if status == "planned":
                out.append(self._start_intent(wf, w, cur, exp_id, dim, control, arms))
            elif status == "running":
                out += self._look(wf, w, cur, exp_id, dim, control, arms, started)
            elif status == "promoted":
                out += self._decay_watch(wf, w, exp_id, "default", dim, control, winner, json.loads(notes or "{}"))
        # winners promoted inside a segment cohort are watched for decay too
        for exp_id, cid, dim, control, winner, notes in self.s.q(
                "SELECT exp_id, cohort_id, dim, control, winner, notes FROM experiments "
                "WHERE wf=? AND status='promoted' AND cohort_id!='default'", wf):
            if dim not in busy_dims:
                out += self._decay_watch(wf, w, exp_id, cid, dim, control, winner, json.loads(notes or "{}"))
        return out

    def _retired(self, wf, dim):
        """Options that lost (pruned, or a winner that faded) sit out RETIRE_MIN before being tested again."""
        r = self.s.get(f"retired:{wf}:{dim}", {})
        if isinstance(r, list):
            r = {o: self.s.now for o in r}
        return {o for o, m in r.items() if self.s.now - m < RETIRE_MIN}

    def _retire(self, wf, dim, opts, db):
        r = self.s.get(f"retired:{wf}:{dim}", {})
        if isinstance(r, list):
            r = {o: self.s.now for o in r}
        for o in opts:
            r[o] = self.s.now
        self.s.put(f"retired:{wf}:{dim}", r, db)

    def _plan_experiment(self, wf, w, cur, dim):
        d = dist(cur["config"], "default", dim)
        control = max(d, key=d.get)
        bad = set(self.s.get(f"did_bad:{wf}", {})) if dim == "caller_id" else set()
        ch = [o for o in w["options"][dim] if o != control and o not in self._retired(wf, dim) and o not in bad]
        # use what we already learned: don't re-test an option our own data already shows is worse than control
        metric = metric_of(w)
        cr = sn(self.sums(wf, f"{dim}={control}|cohort=default", 0), metric)
        known_worse = {}
        for o in ch:
            orr = sn(self.sums(wf, f"{dim}={o}|cohort=default", 0), metric)
            if orr[1] >= 300 and cr[1] >= 300:
                z = two_prop_z(orr[0], orr[1], cr[0], cr[1])
                if z < -1.0:
                    known_worse[o] = round(z, 2)
        ch = [o for o in ch if o not in known_worse][:3]
        if not ch:
            if known_worse and not self.s.get(f"nothing_to_test:{wf}:{dim}:{control}"):
                with self.s.tx() as db:
                    self.s.put(f"nothing_to_test:{wf}:{dim}:{control}", True, db)
                    self.s.decide(wf, "experiment_skipped", f"{dim}: every alternative already measured worse "
                                  f"than {control}", {"z_vs_control": known_worse}, db=db)
            return
        arms = {control: 1 - EXPLORE_TOTAL, **{o: EXPLORE_TOTAL / len(ch) for o in ch}}
        n = self.s.q1("SELECT COUNT(*) FROM experiments WHERE wf=?", wf)[0]
        exp_id = f"{wf}:{dim}:{n + 1}"
        need = N_MIN[metric_of(w)]
        with self.s.tx() as db:
            db.execute("INSERT INTO experiments (exp_id, wf, cohort_id, dim, metric, status, control, arms) "
                       "VALUES (?,?,?,?,?,?,?,?)", (exp_id, wf, "default", dim, metric_of(w), "planned", control,
                                                    json.dumps(arms)))
            self.s.decide(wf, "experiment_planned", f"{exp_id}: {control} vs {ch} on {metric_of(w)}",
                          {"arms": arms, "min_per_arm": need, "alpha_per_look": ALPHA_LOOK}, db=db)

    def _arm_stats(self, wf, dim, opts, h_from, h_to=None, cohort="default"):
        return {o: self.sums(wf, f"{dim}={o}|cohort={cohort}", h_from, h_to) for o in opts}

    def _start_intent(self, wf, w, cur, exp_id, dim, control, arms):
        b = self.s.get(f"baseline:{wf}")
        per_day = b["conn_per_day"] if metric_of(w) == "engagement_rate" else b["dials_per_day"]
        days = N_MIN[metric_of(w)] / max(per_day * min(arms.values()), 1)
        return {
            "key": f"exp_start:{exp_id}", "kind": "exp_start", "exp_id": exp_id, "urgent": False,
            "operational": dim == "caller_id", "alloc": {"default": {dim: arms}},
            "summary": f"Start test on {dim}: {', '.join(f'{o} {v:.0%}' for o, v in arms.items())}",
            "rationale": (f"Test {dim} options against the current {control} on {metric_of(w)}. Challengers get "
                          f"{EXPLORE_TOTAL:.0%} of traffic in total, so the downside is capped. We need "
                          f"{N_MIN[metric_of(w)]} per arm before deciding (≈{days:.1f} days)."),
            "impact": 0.05,   # honest: exploration has no expected lift yet
            "dry_run": {"history": "history ran on the default config only; no data for challengers",
                        "control_history": self._hist_option(wf, dim, control),
                        "worst_case": f"if every challenger were 10% worse, workflow {metric_of(w)} drops "
                                      f"{EXPLORE_TOTAL * 10:.0f}% relative while the test runs"},
        }

    def _hist_option(self, wf, dim, o):
        r = self.sums(wf, f"{dim}={o}", None, 0)
        return {"dials": r[0], "conn": r[1], "pickup": round(rate(r[1], r[0]), 4),
                "engagement": round(rate(r[2], r[1]), 4)}

    def _look(self, wf, w, cur, exp_id, dim, control, arms, started):
        """One look per day, at the start of approver hours, so stats aren't peeked at every tick."""
        lo = max(w["governance"]["approver_hours"][0],
                 CLIENT_PREFS.get(w["tenant_id"], {}).get("earliest_hour", 0))
        today, rem = divmod(self.s.now, DAY)
        look = self.s.get(f"look:{exp_id}")
        if not (look and look.get("day") == today) and rem // 60 >= lo and started // DAY < today:
            look = self._evaluate(wf, w, cur, exp_id, dim, control, arms, started)
            look["day"] = today
            with self.s.tx() as db:
                self.s.put(f"look:{exp_id}", look, db)
                self.s.decide(wf, "experiment_look", f"{exp_id}: {look['verdict']} — {look.get('reason', '')}",
                              look, db=db)
        if not look or look["verdict"] == "continue":
            return []
        metric = metric_of(w)
        A = look["arms"]
        if look["verdict"] == "promote":
            win = look["winner"]
            new = {win: 1 - HOLDOUT, control: HOLDOUT}
            if dim == "caller_id":   # spread load: winner capped, the rest across the other healthy numbers
                others = [o for o in arms if o != win]
                new = {win: DID_MAX_SHARE, **{o: (1 - DID_MAX_SHARE) / len(others) for o in others}}
            protect = look.get("protect", [])
            lift = A[win]["rate"] / max(A[control]["rate"], 1e-9) - 1
            alloc = {"default": {dim: new}}
            for c in protect:
                alloc[c["id"]] = {dim: {control: 1.0}}
            return [{
                "key": f"exp_promote:{exp_id}:{win}", "kind": "exp_promote", "exp_id": exp_id, "winner": win,
                "control": control, "urgent": False, "operational": dim == "caller_id", "alloc": alloc,
                "new_cohorts": [{"id": c["id"], "where": c["where"], "reason":
                                 f"{win} was worse for this segment; keeps {control}"} for c in protect],
                "summary": f"Promote {dim} {win} (+{lift:.1%} {metric} vs {control}); keep {HOLDOUT:.0%} holdout"
                           + (f"; keep {control} for {[p['id'] for p in protect]}" if protect else ""),
                "rationale": (f"{win} beat {control} on {metric}: {A[win]['s']}/{A[win]['n']} vs "
                              f"{A[control]['s']}/{A[control]['n']} (Holm-adjusted one-sided p<{ALPHA_LOOK}). "
                              f"Guardrail {guard_of(w)} checked. {HOLDOUT:.0%} stays on {control} to see if the win fades."),
                "impact": min(1.0, max(0.05, lift * (new[win] - arms.get(win, 0)) / 0.10)),
                "dry_run": {"experiment_arms": A, "expected_rate_after": self._expected(A, new),
                            "expected_rate_now": self._expected(A, arms), "protected_cohorts": protect},
            }]
        if look["verdict"] == "segment_promote":
            sw = look["segment"]
            new = {sw["winner"]: 1 - HOLDOUT, control: HOLDOUT}
            return [{
                "key": f"seg_promote:{exp_id}:{sw['id']}:{sw['winner']}", "kind": "seg_promote", "exp_id": exp_id,
                "cohort": sw["id"], "dim": dim, "winner": sw["winner"], "control": control, "urgent": False,
                "operational": False, "alloc": {sw["id"]: {dim: new}},
                "new_cohorts": [{"id": sw["id"], "where": sw["where"],
                                 "reason": f"{sw['winner']} wins on {metric} for this segment"}],
                "ref": sw["stats"][sw["winner"]], "ref_c": sw["stats"][control],
                "summary": f"For cohort {sw['id']}: use {dim} {sw['winner']} (+{sw['lift']:.1%} {metric} vs {control})",
                "rationale": (f"Within {sw['where']}, {sw['winner']} {sw['stats'][sw['winner']]} vs {control} "
                              f"{sw['stats'][control]} (Holm over {look['segment_tests']} segment tests, p<{ALPHA_LOOK}). "
                              f"No overall winner, so only this cohort changes."),
                "impact": min(1.0, max(0.05, sw["lift"] * sw["share"] / 0.10)),
                "dry_run": {"segment": sw, "workflow_arms": A},
            }]
        if look["verdict"] in ("prune", "close"):
            new = {o: v for o, v in arms.items() if o not in look["losers"]}
            if look["verdict"] == "close" or len(new) <= 1:
                new = {control: 1.0}
            s = sum(new.values())
            new = {o: v / s for o, v in new.items()}
            if new == arms:
                return []
            return [{
                "key": f"exp_{look['verdict']}:{exp_id}:{','.join(sorted(new))}", "kind": f"exp_{look['verdict']}",
                "exp_id": exp_id, "new_arms": new, "losers": look["losers"], "urgent": False,
                "operational": dim == "caller_id",
                "alloc": {"default": {dim: new}},
                "summary": (f"Stop testing {look['losers']} on {dim} (worse than {control})" if look["verdict"] == "prune"
                            else f"End {dim} test: every challenger lost to {control}"),
                "rationale": look["reason"],
                "impact": min(1.0, max(0.05, sum(arms[o] for o in look["losers"]))),
                "dry_run": {"experiment_arms": A, "expected_rate_after": self._expected(A, new),
                            "expected_rate_now": self._expected(A, arms)},
            }]
        return []

    @staticmethod
    def _expected(arm_stats, alloc):
        tot = sum(alloc.values()) or 1
        return round(sum(arm_stats.get(o, {}).get("rate", 0) * v / tot for o, v in alloc.items()), 4)

    def _evaluate(self, wf, w, cur, exp_id, dim, control, arms, started):
        metric, guard = metric_of(w), guard_of(w)
        h = started // 60 + 1
        st = self._arm_stats(wf, dim, arms, h)
        A = {}
        for o, r in st.items():
            s, n = sn(r, metric)
            gs, gn = sn(r, guard)
            lo, hi = wilson(s, n)
            A[o] = {"s": s, "n": n, "rate": round(rate(s, n), 4), "ci": [round(lo, 4), round(hi, 4)],
                    "guard_rate": round(rate(gs, gn), 4), "guard_n": gn}
        res = {"arms": A, "verdict": "continue", "losers": [], "winner": None}
        cs, cn = A[control]["s"], A[control]["n"]
        ch = [o for o in arms if o != control]
        need = N_MIN[metric]
        ready = [o for o in ch if A[o]["n"] >= need]
        if not ready:
            res["reason"] = f"waiting for {need} per arm"
            return res
        z = {o: two_prop_z(A[o]["s"], A[o]["n"], cs, cn) for o in ready}
        winners = holm({o: norm_sf(z[o]) for o in ready}, ALPHA_LOOK)
        losers = holm({o: norm_sf(-z[o]) for o in ready}, ALPHA_LOOK)
        # an arm can look fine overall and fade later: test the last RECENT_H hours too (separate Holm family)
        h_recent = max(h, self.now_h() - RECENT_H)
        if h_recent > h:
            rs = self._arm_stats(wf, dim, arms, h_recent)
            rc = sn(rs[control], metric)
            zr = {o: two_prop_z(*sn(rs[o], metric), *rc) for o in ch if sn(rs[o], metric)[1] >= need // 2}
            faded = holm({o: norm_sf(-v) for o, v in zr.items()}, ALPHA_LOOK)
            if faded - losers:
                res["faded_recently"] = {o: round(zr[o], 2) for o in faded}
            losers |= faded
            winners -= faded
            # a winner must still be ahead lately, or we'd promote something that is already fading
            not_lately = {o for o in winners if zr.get(o, 0.0) < 1.28}   # no recent data = no promotion
            # trend guard: over the last 24h the lift must still be at least half the all-time lift (point estimate)
            r24 = self._arm_stats(wf, dim, arms, max(h, self.now_h() - 24))
            c24 = rate(*sn(r24[control], metric))
            for o in winners - not_lately:
                lift_all = A[o]["rate"] - A[control]["rate"]
                lift_24 = rate(*sn(r24[o], metric)) - c24
                if lift_24 < 0.5 * lift_all:
                    not_lately.add(o)
                    res.setdefault("trend_guard", {})[o] = {"lift_all": round(lift_all, 4), "lift_24h": round(lift_24, 4)}
            if not_lately:
                res["not_ahead_recently"] = {o: round(zr.get(o, 0.0), 2) for o in not_lately}
            winners -= not_lately
        res["z"] = {o: round(v, 2) for o, v in z.items()}
        ok = []
        max_drop = list(w["objective"]["guardrail"].values())[0]
        for o in winners:   # guardrail: block a winner whose other KPI is clearly worse
            gz = two_prop_z(*sn(st[o], guard), *sn(st[control], guard))
            if gz < -2.33 and A[control]["guard_rate"] - A[o]["guard_rate"] > max_drop / 2:
                res.setdefault("guard_blocked", []).append(o)
            else:
                ok.append(o)
        if ok:
            win = max(ok, key=lambda o: A[o]["rate"])
            res.update(verdict="promote", winner=win, losers=sorted(losers),
                       reason=f"{win} significantly better than {control}")
            if metric == "engagement_rate":
                res["protect"] = self._harmed_segments(wf, dim, win, control, h, cur)
            return res
        if losers:
            res.update(verdict="close" if set(losers) >= set(ch) else "prune", losers=sorted(losers),
                       reason=f"{sorted(losers)} significantly worse than {control} (Holm one-sided p<{ALPHA_LOOK})")
            return res
        if metric == "engagement_rate":
            seg = self._segment_winner(wf, w, dim, control, ch, h, cur)
            if seg:
                res.update(verdict="segment_promote", segment=seg["best"], segment_tests=seg["tests"],
                           reason=f"{seg['best']['winner']} wins for {seg['best']['where']}")
                return res
        res["reason"] = "no significant difference yet"
        return res

    def _segments(self, wf, dim, opt):
        out = []
        for (k,) in self.s.q("SELECT DISTINCT key FROM agg WHERE wf=? AND key LIKE ?", wf, f"{dim}={opt}|%"):
            f, v = k.split("|", 1)[1].split("=", 1)
            if f in FEATURES:
                out.append((f, v))
        return sorted(out)

    @staticmethod
    def _cid(f, v):
        return re.sub(r"[^a-z0-9]+", "_", f"{f}_{v}".lower().replace("+", "plus")).strip("_")

    def _segment_winner(self, wf, w, dim, control, ch, h, cur):
        """No overall winner — is there a segment where a challenger clearly wins? Holm over every
        (segment, challenger) test so slicing many ways doesn't manufacture winners."""
        existing = {c["id"] for c in cur["config"]["cohorts"]}
        if len(existing) >= MAX_COHORTS:
            return None
        pv, info = {}, {}
        total = self.sums(wf, "all", h)[1] or 1
        for f, v in self._segments(wf, dim, control):
            cid = self._cid(f, v)
            if cid in existing:
                continue
            b = sn(self.sums(wf, f"{dim}={control}|{f}={v}", h), "engagement_rate")
            if b[1] < SEG_MIN:
                continue
            for o in ch:
                a = sn(self.sums(wf, f"{dim}={o}|{f}={v}", h), "engagement_rate")
                if a[1] < SEG_MIN:
                    continue
                zz = two_prop_z(a[0], a[1], b[0], b[1])
                pv[(f, v, o)] = norm_sf(zz)
                seg_conn = sn(self.sums(wf, f"seg:{f}={v}", h), "engagement_rate")[1]
                info[(f, v, o)] = {"id": cid, "where": {f: [v]}, "winner": o, "z": round(zz, 2),
                                   "lift": rate(*a) / max(rate(*b), 1e-9) - 1, "share": seg_conn / total,
                                   "stats": {o: f"{a[0]}/{a[1]}", control: f"{b[0]}/{b[1]}"}}
        if not pv:
            return None
        hits = holm(pv, ALPHA_LOOK)
        h_recent = self.now_h() - RECENT_H
        if h_recent > h:   # the segment winner must still be ahead lately
            keep = set()
            for f, v, o in hits:
                a = sn(self.sums(wf, f"{dim}={o}|{f}={v}", h_recent), "engagement_rate")
                b = sn(self.sums(wf, f"{dim}={control}|{f}={v}", h_recent), "engagement_rate")
                if a[1] >= SEG_MIN // 2 and two_prop_z(a[0], a[1], b[0], b[1]) >= 1.28:
                    keep.add((f, v, o))
            hits = keep
        if not hits:
            return None
        best = max(hits, key=lambda k: info[k]["lift"] * info[k]["share"])
        return {"best": info[best], "tests": len(pv)}

    def _harmed_segments(self, wf, dim, win, control, h, cur):
        """Before promoting, check the winner isn't clearly worse for some segment. Such a segment becomes a
        cohort that keeps the control: an improvement that hurts a cohort is worth less than nothing."""
        existing = {c["id"] for c in cur["config"]["cohorts"]}
        pv, detail = {}, {}
        for f, v in self._segments(wf, dim, win):
            if self._cid(f, v) in existing:
                continue
            a = sn(self.sums(wf, f"{dim}={win}|{f}={v}", h), "engagement_rate")
            b = sn(self.sums(wf, f"{dim}={control}|{f}={v}", h), "engagement_rate")
            if a[1] < SEG_MIN or b[1] < SEG_MIN:
                continue
            pv[(f, v)] = norm_sf(-two_prop_z(a[0], a[1], b[0], b[1]))
            detail[(f, v)] = (a, b)
        harmed = holm(pv, 0.05) if pv else set()
        room = MAX_COHORTS - len(existing)
        out = []
        for f, v in sorted(harmed, key=lambda fv: pv[fv])[:max(room, 0)]:
            a, b = detail[(f, v)]
            out.append({"id": self._cid(f, v), "where": {f: [v]}, "keep": control,
                        "evidence": {"winner": a, "control": b, "p": round(pv[(f, v)], 5)}})
        return out

    def _decay_watch(self, wf, w, exp_id, cohort, dim, control, winner, notes):
        metric = metric_of(w)
        h1 = self.now_h()
        promo_h = notes.get("promo_h", h1)
        # 24h window; widen to 48h when the holdout is too thin in a day (low pickup → few connected calls)
        if h1 - DECAY_WINDOW_H < promo_h:    # need one full window after promotion
            return []
        for win_h in (DECAY_WINDOW_H, 2 * DECAY_WINDOW_H):
            h0 = h1 - win_h
            if h0 < promo_h:    # 48h not available yet: stay with the 24h numbers
                win_h = DECAY_WINDOW_H
                break
            r = self._arm_stats(wf, dim, [winner, control], h0, h1, cohort)
            ws, wn = sn(r[winner], metric)
            hs, hn = sn(r[control], metric)
            if hn >= 150:
                break
        ref_s, ref_n = notes.get("ref_s", 0), notes.get("ref_n", 0)
        ref_cs, ref_cn = notes.get("ref_cs", 0), notes.get("ref_cn", 0)
        if wn < 300 or hn < 150 or ref_n == 0:
            return []   # holdout too thin: comparing the winner to its own past is confounded by drift, so wait
        # decay = the winner's lead over the holdout (same hours, same drift) has shrunk, or it's now behind
        cur_up = rate(ws, wn) - rate(hs, hn)
        ref_up = notes.get("ref_uplift", 0)
        var = lambda s_, n_: max(rate(s_, n_) * (1 - rate(s_, n_)), 1e-6) / max(n_, 1)
        se = math.sqrt(var(ws, wn) + var(hs, hn) + (var(ref_s, ref_n) + var(ref_cs, ref_cn) if ref_cn else 0))
        z_up = (cur_up - ref_up) / se
        z_hold = two_prop_z(ws, wn, hs, hn)
        z_self = two_prop_z(ws, wn, ref_s, ref_n)
        # A shrinking lead is not a loss: only roll back once the winner is no longer ahead of the holdout.
        # Rolling windows re-tested every tick are a multiple-testing trap, so we test every 6h and need the
        # signal on two consecutive checks before acting (≈ +6h detection delay, far fewer false rollbacks).
        sig = cur_up <= 0 and (z_up < -3.0 or z_hold < -2.58)
        streak_key = f"decay_streak:{exp_id}"
        streak = self.s.get(streak_key, {"n": 0, "h": -1})
        if h1 % 6 == 0 and streak["h"] != h1:
            streak = {"n": streak["n"] + 1 if sig else 0, "h": h1}
            self.s.put(streak_key, streak)
        decayed = streak["n"] >= 2
        if not decayed:
            if z_up < -2.58 and not self.s.get(f"shrink_logged:{exp_id}"):
                note = ("still ahead, keeping it" if cur_up > 0 else
                        "no longer ahead; rolling back if the next 6-hourly check agrees")
                with self.s.tx() as db:
                    self.s.put(f"shrink_logged:{exp_id}", True, db)
                    self.s.decide(wf, "lead_shrinking", f"{exp_id} [{cohort}]: {winner}'s lead fell from "
                                  f"{ref_up:+.1%} to {cur_up:+.1%}; {note}", {"z": round(z_up, 2)}, db=db)
            return []
        info = {"cohort": cohort, "window_h": win_h, "winner_recent": [ws, wn], "holdout_recent": [hs, hn],
                "winner_at_promotion": [ref_s, ref_n], "uplift_then": round(ref_up, 4), "uplift_now": round(cur_up, 4),
                "z_uplift_drop": round(z_up, 2), "z_vs_holdout": round(z_hold, 2), "z_self": round(z_self, 2)}
        if not self.s.get(f"decay_logged:{exp_id}"):
            with self.s.tx() as db:
                self.s.put(f"decay_logged:{exp_id}", True, db)
                self.s.decide(wf, "decay_detected", f"{exp_id} [{cohort}]: {winner} stopped winning", info, db=db)
        return [{
            "key": f"exp_rollback:{exp_id}", "kind": "exp_rollback", "exp_id": exp_id, "winner": winner,
            "dim": dim, "urgent": True, "operational": dim == "caller_id", "alloc": {cohort: {dim: {control: 1.0}}},
            "summary": f"Roll back {dim} {winner} → {control} for {cohort}: its advantage has faded",
            "rationale": (f"Last {win_h}h: {winner} {rate(ws, wn):.1%} (n={wn}) vs holdout {control} "
                          f"{rate(hs, hn):.1%} (n={hn}); its lead went from {ref_up:+.1%} to {cur_up:+.1%} "
                          f"(z={z_up:.1f})."),
            "impact": min(1.0, max(0.1, (ref_up - cur_up) / max(rate(hs, hn), 1e-6) / 0.10)), "dry_run": info,
        }]

    # ------------------------------------------------------------------ apply callback (idempotent)
    def on_applied(self, wf, intents, version, db):
        for i in intents:
            k = i["kind"]
            for c in i.get("new_cohorts", []):
                db.execute("INSERT OR IGNORE INTO cohorts VALUES (?,?,?,?,?)",
                           (wf, c["id"], json.dumps(c["where"]), self.s.now, c["reason"]))
            if k == "exp_start":
                db.execute("UPDATE experiments SET status='running', started_minute=?, start_day=? "
                           "WHERE exp_id=? AND status='planned'", (self.s.now, self.s.now // DAY, i["exp_id"]))
            elif k == "exp_promote":
                A = (self.s.get(f"look:{i['exp_id']}") or {}).get("arms", {})
                win, ctrl = i["winner"], i["control"]
                notes = {"promo_h": self.s.now // 60, "ref_s": A.get(win, {}).get("s", 0),
                         "ref_n": A.get(win, {}).get("n", 0), "ref_cs": A.get(ctrl, {}).get("s", 0),
                         "ref_cn": A.get(ctrl, {}).get("n", 0),
                         "ref_uplift": A.get(win, {}).get("rate", 0) - A.get(ctrl, {}).get("rate", 0)}
                db.execute("UPDATE experiments SET status='promoted', winner=?, decided_minute=?, promo_day=?, "
                           "notes=? WHERE exp_id=? AND status='running'",
                           (win, self.s.now, self.s.now // DAY, json.dumps(notes), i["exp_id"]))
            elif k == "seg_promote":
                s_, n_ = (int(x) for x in i["ref"].split("/"))
                cs_, cn_ = (int(x) for x in i["ref_c"].split("/"))
                eid = f"{i['exp_id']}@{i['cohort']}"
                notes = {"promo_h": self.s.now // 60, "ref_s": s_, "ref_n": n_, "ref_cs": cs_, "ref_cn": cn_,
                         "ref_uplift": rate(s_, n_) - rate(cs_, cn_)}
                db.execute("INSERT OR IGNORE INTO experiments (exp_id, wf, cohort_id, dim, metric, status, control,"
                           " arms, winner, started_minute, decided_minute, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (eid, wf, i["cohort"], i["dim"], "engagement_rate", "promoted", i["control"],
                            json.dumps(i["alloc"][i["cohort"]][i["dim"]]), i["winner"], self.s.now, self.s.now,
                            json.dumps(notes)))
            elif k == "exp_prune":
                db.execute("UPDATE experiments SET arms=? WHERE exp_id=?", (json.dumps(i["new_arms"]), i["exp_id"]))
                self._retire(wf, i["exp_id"].split(":")[1], i.get("losers", []), db)
            elif k == "exp_close":
                self._retire(wf, i["exp_id"].split(":")[1], i.get("losers", []), db)
                db.execute("UPDATE experiments SET status='closed', decided_minute=?, notes=? WHERE exp_id=?",
                           (self.s.now, "every challenger lost", i["exp_id"]))
            elif k == "exp_rollback":
                db.execute("UPDATE experiments SET status='rolled_back', decided_minute=? WHERE exp_id=?",
                           (self.s.now, i["exp_id"]))
                self._retire(wf, i["dim"], [i["winner"]], db)
            elif k == "did_fix":
                # the caller-ID mix changed under any running caller-ID test: end it, a new one re-plans
                db.execute("UPDATE experiments SET status='closed', decided_minute=?, notes=? WHERE wf=? AND "
                           "dim='caller_id' AND status IN ('planned','running','promoted')",
                           (self.s.now, "caller ID quarantined", wf))
            elif k == "prompt_fix":
                inc = self.s.get(f"incident:{wf}")
                if inc and inc["id"] == i["incident"] and inc["state"] != "verifying":
                    inc["state"] = "verifying"
                    inc["fixed_h"] = self.s.now // 60 + 1
                    inc["fixed_minute"] = self.s.now
                    self.s.put(f"incident:{wf}", inc, db)

    # ------------------------------------------------------------------ planning: batch + route
    def plan(self, wf, w, cur, intents):
        open_keys = self.gov.open_intent_keys(wf)
        intents = [i for i in intents if i["key"] not in open_keys]
        if not intents:
            return
        old = cur["config"]
        auto, appr = [], []
        for i in intents:
            if i["operational"]:
                step = self._clamp(wf, old, self._compose(old, [i]))
                if step is not None and self.gov.auto_allowed(wf, old, step):
                    auto.append((i, step))
                    continue
            appr.append(i)
        for i, step in auto[:1]:     # one auto change per tick; the next tick re-plans on the new version
            self.gov.submit_auto(wf, step, [i], i["rationale"], i.get("evidence"))
            return
        if not appr:
            return
        urgent = any(i["urgent"] for i in appr)
        if not urgent and self._recent_refusal(wf):
            return
        ok, _why = self.gov.can_request(wf, urgent)
        if not ok:
            return
        if urgent:   # urgent ones go alone, so a judgement-call rejection on routine stuff can't block a fix
            appr = [i for i in appr if i["urgent"]]
        # never batch two intents that set the same (cohort, dim): keep the first (policies order by priority)
        seen, batch = set(), []
        for i in appr:
            slots = {(c, d) for c, dd in i.get("alloc", {}).items() for d in dd} | ({"prompt"} if i.get("prompt") else set())
            if slots & seen:
                continue
            seen |= slots
            batch.append(i)
        new = self._compose(old, batch)
        if not changed_dims(old, new):
            return
        self.gov.submit_approval(wf, new, batch, urgent, self._payload(wf, w, old, new, batch))

    def _recent_refusal(self, wf):
        r = self.s.q1("SELECT MAX(decided_minute) FROM proposals WHERE wf=? AND status IN ('rejected','expired')", wf)
        return r[0] is not None and self.s.now - r[0] < 180

    @staticmethod
    def _compose(old, intents):
        new = copy.deepcopy(old)
        for i in intents:
            for c in i.get("new_cohorts", []):
                if c["id"] not in {x["id"] for x in new["cohorts"]} and len(new["cohorts"]) < 20:
                    # appended: leads already in an earlier cohort stay there (segment tests only use default-cohort calls)
                    new["cohorts"].append({"id": c["id"], "where": c["where"]})
            for k, dims in (i.get("alloc") or {}).items():
                for dim, d in dims.items():
                    new["allocations"].setdefault(k, {})[dim] = dict(d)
            if i.get("prompt"):
                new["prompt_version"] = i["prompt"]
        return new

    def _clamp(self, wf, old, new):
        """Move toward `new` by at most the policy's max_shift (TV distance). Returns the step config."""
        cap = self.wfs[wf]["governance"]["auto_apply"].get("max_shift", 0)
        sh = max_shift(old, new)
        if sh <= cap + 1e-9:
            return new
        if cap <= 0:
            return None
        f = cap / sh * 0.999
        step = copy.deepcopy(new)
        for k in set(old["allocations"]) | set(new["allocations"]):
            for dim in ("welcome_message", "voice", "caller_id"):
                a, b = dist(old, k, dim), dist(new, k, dim)
                if a == b:
                    continue
                mix = {o: a.get(o, 0) * (1 - f) + b.get(o, 0) * f for o in set(a) | set(b)}
                step["allocations"].setdefault(k, {})[dim] = {o: round(v, 6) for o, v in mix.items() if v > 1e-6}
        return step

    def _payload(self, wf, w, old, new, intents):
        dims = changed_dims(old, new)
        diff, share = {}, 0.0
        keys = set(old["allocations"]) | set(new["allocations"])
        total = self.sums(wf, "all", self.now_h() - 72)[0] or 1
        for d in dims:
            if d in ("welcome_message", "voice", "caller_id"):
                for k in sorted(keys):
                    a, b = dist(old, k, d), dist(new, k, d)
                    if a != b:
                        diff.setdefault(d, {})[k] = {"from": a, "to": b}
                        frac = 1.0 if k == "default" else self._cohort_share(wf, new, k, total)
                        share = max(share, tv(a, b) * frac)
            elif d == "prompt_version":
                diff[d] = {"from": old["prompt_version"], "to": new["prompt_version"]}
                share = 1.0
            elif d == "cohorts":
                diff[d] = {"added": [c for c in new["cohorts"] if c not in old["cohorts"]]}
        ev = {}
        for i in intents:
            ev.update(i.get("evidence") or {})
        return {
            "change_summary": " + ".join(i["summary"] for i in intents),
            "diff": diff or {"note": "no visible change"},
            # leads per day whose experience changes: moved share of a day's batch
            "affected_leads": int(round(w["daily_batch"]["size"] * max(share, 0.01))),
            "dry_run": {i["key"]: i["dry_run"] for i in intents},
            "impact_score": round(max(i["impact"] for i in intents), 3),
            "rationale": " | ".join(i["rationale"] for i in intents),
            "evidence": ev,
        }

    def _cohort_share(self, wf, cfg, cid, total):
        c = next((c for c in cfg["cohorts"] if c["id"] == cid), None)
        if not c or len(c["where"]) != 1:
            return 1.0
        f, vals = next(iter(c["where"].items()))
        n = sum(self.sums(wf, f"seg:{f}={v}", self.now_h() - 72)[0] for v in vals)
        return min(1.0, n / total)
