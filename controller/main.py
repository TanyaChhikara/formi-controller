"""Controller entry point: python -m controller.main --url http://127.0.0.1:8700 [--db state/x.db]

Loop:  ingest new chunks → refresh configs → reconcile proposals → policies propose → governance sends
       → advance the simulator 30 minutes → repeat until the scenario finishes.
Kill it anywhere and start it again with the same --db: it resumes (see SUBMISSION.md §9).
"""
from __future__ import annotations

import argparse
import logging
import os
import resource
import shutil
import sys
import time

from .client import Sim
from .governance import Governance
from .ingest import Ingestor
from .policies import Brain
from .store import Store
from .util import fmt_minute, set_origin

TARGET_STEP = 30   # minutes per loop; rounded to a multiple of the scenario's tick
log = logging.getLogger("controller")


def open_store(sim, path):
    """Same world → resume. Different world (sim restarted, other scenario) → archive the old DB, start fresh."""
    st = sim.get("/sim/state")
    hist = sim.get("/events/chunks", kind="history", after=-1)
    sig = f"{st['scenario']}:{hist[0]['last_event_id'] if hist else 0}"
    if os.path.exists(path):
        s = Store(path)
        old_sig, old_min = s.get("world_sig"), s.get("sim_minute", 0)
        if old_sig == sig and old_min <= st["sim_minute"]:
            log.info("resuming from %s at %s", path, fmt_minute(old_min))
            return s
        s.db.close()
        arch = f"{path}.{int(time.time())}.old"
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(path + ext):
                shutil.move(path + ext, arch + ext)
        log.info("store belongs to another world (%s); archived to %s", old_sig, arch)
    s = Store(path)
    s.put("world_sig", sig)
    return s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8700")
    ap.add_argument("--db", default=None)
    ap.add_argument("--stop-at-minute", type=int, default=None, help="exit early (for crash tests)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    sim = Sim(a.url)
    sim.wait_ready()
    st0 = sim.get("/sim/state")
    set_origin(st0["ts"], st0["sim_minute"])
    tick = int(st0.get("tick_minutes") or 15)
    step = tick * max(1, round(TARGET_STEP / tick))   # the sim rejects steps that aren't a multiple of its tick
    log.info("scenario %s: tick %d min, stepping %d min", st0["scenario"], tick, step)
    db = a.db or os.environ.get("CONTROLLER_DB") or f"state/{st0['scenario']}.db"
    os.makedirs(os.path.dirname(db) or ".", exist_ok=True)
    store = open_store(sim, db)
    wfs = {w["workflow_id"]: w for w in sim.get("/workflows")}
    gov = Governance(store, sim, wfs, on_applied=None)
    brain = Brain(store, sim, wfs, gov)
    ing = Ingestor(store, sim)

    store.now = st0["sim_minute"]
    n, s = ing.ingest_pending()
    log.info("caught up: %d events in %.1fs", n, s)
    brain.bootstrap()
    t_start = time.time()
    while True:
        state = sim.get("/sim/state")
        store.now = state["sim_minute"]
        store.put("sim_minute", store.now)
        t0 = time.time()
        n, ing_s = ing.ingest_pending()
        brain.tick(state["credits_remaining"])
        dec_s = time.time() - t0 - ing_s
        pending = store.q1("SELECT COUNT(*) FROM proposals WHERE status IN ('intent','pending','approved','applying')")[0]
        nd = store.q1("SELECT COUNT(*) FROM decisions")[0]
        store.metric(sim_minute=store.now, wall=time.time(), events=n, ingest_s=round(ing_s, 3),
                     decide_s=round(dec_s, 3), credits=state["credits_remaining"], pending=pending, decisions=nd,
                     rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1))
        if store.now % 1440 == 0:
            log.info("%s events=%d ingest=%.1fs decide=%.1fs credits=%.0f pending=%d decisions=%d wall=%.0fs",
                     fmt_minute(store.now), n, ing_s, dec_s, state["credits_remaining"], pending, nd,
                     time.time() - t_start)
        if state["finished"]:
            break
        if a.stop_at_minute is not None and store.now >= a.stop_at_minute:
            log.info("stopping at %s as asked", fmt_minute(store.now))
            return 3
        sim.post("/sim/advance", {"minutes": step})
    log.info("scenario finished at %s; wall %.0fs", fmt_minute(store.now), time.time() - t_start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
