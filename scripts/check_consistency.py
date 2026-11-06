"""Test harness (not the controller): compares the controller's store with what the simulator's API says.
Usage: python scripts/check_consistency.py URL DB"""
import json
import sqlite3
import sys
from collections import Counter

import httpx

url, dbp = sys.argv[1], sys.argv[2]
c = httpx.Client(base_url=url, timeout=300)
db = sqlite3.connect(dbp)
ok = True

# (a) every call event counted exactly once
truth = Counter()
for kind in ("history", "events"):
    for ch in c.get("/events/chunks", params={"kind": kind}).json():
        for line in c.get(f"/events/chunks/{ch['chunk']}").content.splitlines():
            ev = json.loads(line)
            if ev["type"] == "call":
                truth[ev["workflow_id"]] += 1
mine = dict(db.execute("SELECT wf, SUM(dials) FROM agg WHERE key='all' GROUP BY wf").fetchall())
for wf, n in truth.items():
    good = mine.get(wf) == n
    ok &= good
    print(f"calls {wf}: simulator={n} controller={mine.get(wf)} {'OK' if good else 'MISMATCH'}")

# (b) approvals: none applied twice, none approved-but-forgotten, store agrees with the simulator
for w in c.get("/workflows").json():
    wf = w["workflow_id"]
    hist = c.get(f"/workflows/{wf}/config/history").json()
    aids = Counter(h["approval_id"] for h in hist if h.get("approval_id"))
    dup = [a for a, k in aids.items() if k > 1]
    apps = c.get("/approvals", params={"workflow_id": wf}).json()
    mine_status = dict(db.execute("SELECT approval_id, status FROM proposals WHERE wf=? AND approval_id IS NOT NULL",
                                  (wf,)).fetchall())
    # approved-but-unapplied is only OK when we deliberately refused it because its base went stale
    stuck = [a["approval_id"] for a in apps if a["status"] == "approved" and mine_status.get(a["approval_id"]) != "stale"]
    stale = [a["approval_id"] for a in apps if mine_status.get(a["approval_id"]) == "stale"]
    lapsed = [a["approval_id"] for a in apps if a["status"] == "lapsed"]
    disagree = [a["approval_id"] for a in apps if mine_status.get(a["approval_id"]) not in
                (a["status"], "stale" if a["status"] == "approved" else a["status"])]
    good = not dup and not stuck and not lapsed and not disagree
    ok &= good
    print(f"approvals {wf}: {len(apps)} total, applied twice={dup}, approved-but-unapplied={stuck}, lapsed={lapsed}, "
          f"refused-as-stale={stale}, store disagrees={disagree} {'OK' if good else 'PROBLEM'}")
print("CONSISTENT" if ok else "INCONSISTENT")
