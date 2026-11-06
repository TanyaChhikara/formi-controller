"""Ingest-only benchmark: advance the sim and ingest, no decisions. Usage: python scripts/bench_ingest.py URL DB DAYS"""
import os
import resource
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from controller.client import Sim  # noqa: E402
from controller.ingest import Ingestor  # noqa: E402
from controller.store import Store  # noqa: E402

url, db, days = sys.argv[1], sys.argv[2], int(sys.argv[3])
sim = Sim(url)
st = Store(db)
ing = Ingestor(st, sim)
t0 = time.time()
n, s = ing.ingest_pending()
print(f"history: {n} events in {s:.1f}s ({n / max(s, 1e-9):.0f} ev/s)")
for d in range(days):
    t1 = time.time(); adv = 0; tot = 0; ing_s = 0
    for _ in range(48):
        a = time.time(); sim.post("/sim/advance", {"minutes": 30}); adv += time.time() - a
        n, s = ing.ingest_pending(); tot += n; ing_s += s
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"day {d}: {tot} events, wall {time.time() - t1:.1f}s (sim advance {adv:.1f}s, ingest {ing_s:.1f}s,"
          f" {tot / max(ing_s, 1e-9):.0f} ev/s), peak rss {rss:.0f} MB")
