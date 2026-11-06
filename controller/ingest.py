"""Event ingestion (C1). Each chunk is read, folded into counters in memory, and committed in ONE
transaction together with the chunk's cursor row. A kill before COMMIT means the chunk is re-read on
restart; a kill after means it's skipped. Either way nothing is counted twice or lost.

We don't store raw call events: ~850k/day on the load scenario would be ~25M rows over a run for no
benefit. Counters per (workflow, day, hour, key) are all the learning loop needs.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

from .store import Store
from .util import DAY, ts_to_minute

FEATURES = ("lang", "city_tier", "age_band", "value_band")
EXP_DIMS = ("welcome_message", "voice")      # sliced by segment for heterogeneity checks
ALL_DIMS = ("welcome_message", "voice", "caller_id", "prompt_version")


class Ingestor:
    def __init__(self, store: Store, sim):
        self.s = store
        self.sim = sim
        self.leads: dict[str, tuple] = {}
        self._minute_cache: dict[str, tuple] = {}
        for lid, seg in store.q("SELECT lead_id, seg FROM leads"):
            self.leads[lid] = tuple(seg.split("|"))

    def _dh(self, ts):
        # timestamps repeat heavily (all calls in a tick share a ts), so cache the parse
        r = self._minute_cache.get(ts)
        if r is None:
            if len(self._minute_cache) > 50000:
                self._minute_cache.clear()
            d, rem = divmod(ts_to_minute(ts), DAY)
            r = (d, rem // 60)
            self._minute_cache[ts] = r
        return r

    def ingest_pending(self) -> tuple[int, float]:
        """Ingest every chunk (history and events) we haven't committed yet. Returns (events, seconds)."""
        last = self.s.q1("SELECT MAX(n) FROM chunks")[0]
        last = -1 if last is None else last  # chunks commit in order, so the max is a safe cursor
        todo = []
        for kind in ("history", "events"):
            todo += self.sim.get("/events/chunks", kind=kind, after=last)
        todo.sort(key=lambda c: c["chunk"])
        total, t0 = 0, time.time()
        for c in todo:
            total += self._ingest_chunk(c)
        return total, time.time() - t0

    def _ingest_chunk(self, c) -> int:
        n = c["chunk"]
        lines = self.sim.chunk_lines(n)
        agg = defaultdict(lambda: [0, 0, 0, 0])
        new_leads = []
        cfg_events = []
        leads = self.leads
        for line in lines:
            ev = json.loads(line)
            t = ev["type"]
            if t == "call":
                wf = ev["workflow_id"]
                d, h = self._dh(ev["ts"])
                conn = ev["connected"]
                eng = ev["engaged"]
                hal = 1 if conn and ev.get("qa", {}).get("hallucination_flag") else 0
                inc = (1, 1 if conn else 0, 1 if eng else 0, hal)
                var = ev["variant"]
                seg = leads.get(ev["lead_id"])
                cid = ev.get("cohort_id") or "default"
                keys = ["all", f"cv={ev['config_version']}", f"cohort={cid}"]
                for dim in ALL_DIMS:
                    keys.append(f"{dim}={var[dim]}")
                keys.append(f"caller_id={var['caller_id']}|cohort={cid}")
                for dim in EXP_DIMS:
                    keys.append(f"{dim}={var[dim]}|cohort={cid}")
                    if seg:
                        for f, v in zip(FEATURES, seg):
                            keys.append(f"{dim}={var[dim]}|{f}={v}")
                if seg:
                    for f, v in zip(FEATURES, seg):
                        keys.append(f"seg:{f}={v}")
                for k in keys:
                    a = agg[(wf, d, h, k)]
                    a[0] += inc[0]; a[1] += inc[1]; a[2] += inc[2]; a[3] += inc[3]
            elif t == "lead":
                f = ev["features"]
                seg = tuple(f[k] for k in FEATURES)
                leads[ev["lead_id"]] = seg
                new_leads.append((ev["lead_id"], "|".join(seg)))
            elif t == "config_changed":
                cfg_events.append(ev)
        with self.s.tx() as db:
            db.executemany("INSERT OR REPLACE INTO leads VALUES (?,?)", new_leads)
            db.executemany(
                "INSERT INTO agg VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(wf,day,hour,key) DO UPDATE SET "
                "dials=dials+excluded.dials, conn=conn+excluded.conn, eng=eng+excluded.eng, "
                "halluc=halluc+excluded.halluc",
                [(*k, *v) for k, v in agg.items()])
            for ev in cfg_events:
                hist = c["kind"] == "history"
                db.execute(
                    "INSERT OR IGNORE INTO config_versions (wf, version, actor, sim_minute, changed_dims,"
                    " proposal_id, approval_id, config, handled) VALUES (?,?,?,?,?,?,?,?,?)",
                    (ev["workflow_id"], ev["version"], ev["actor"], ts_to_minute(ev["ts"]),
                     json.dumps(ev.get("changed_dims")), ev.get("proposal_id"), ev.get("approval_id"), None,
                     1 if hist else 0))
            db.execute("INSERT INTO chunks VALUES (?,?,?,?)", (n, c["kind"], len(lines), time.time()))
        return len(lines)
