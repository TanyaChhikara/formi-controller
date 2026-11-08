#!/usr/bin/env bash
# Crash-recovery evidence: kill -9 the controller at random moments during public_02, restart it each time,
# let it finish, then check (a) every event was counted exactly once, (b) no approval was applied twice or lost,
# (c) the run graded normally.   Usage: scripts/crash_test.sh [kills=5]
set -uo pipefail
cd "$(dirname "$0")/.."
KILLS=${1:-5}; PORT=8710; URL=http://127.0.0.1:$PORT
LOG=reports/crash_test.log; : > $LOG
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/crash02 --force --port $PORT > /tmp/sim_crash.log 2>&1 &
SIM=$!; trap 'kill $SIM 2>/dev/null' EXIT
until grep -q ready /tmp/sim_crash.log; do
  kill -0 $SIM 2>/dev/null || { echo "simulator failed to start:"; cat /tmp/sim_crash.log; exit 1; }
  sleep 1
done
export CONTROLLER_DB=state/crash02.db; rm -f $CONTROLLER_DB*
for i in $(seq 1 "$KILLS"); do
  python -m controller.main --url $URL >> $LOG 2>&1 &
  PID=$!
  T=$(python -c "import random; print(round(random.uniform(1.5, 4.0), 1))")
  sleep "$T"
  kill -9 $PID 2>/dev/null && wait $PID 2>/dev/null
  echo "=== kill -9 #$i after ${T}s at $(curl -s $URL/sim/state | python -c 'import sys,json; s=json.load(sys.stdin); print(s["ts"])')" | tee -a $LOG
done
echo "=== final restart, run to completion" | tee -a $LOG
python -m controller.main --url $URL >> $LOG 2>&1
echo "=== exit code $?" | tee -a $LOG
python scripts/check_consistency.py $URL $CONTROLLER_DB | tee -a $LOG
[ -d runs/base02 ] || python -m sim baseline --scenario scenarios/public_02_incidents.yaml --run-dir runs/base02
python -m sim grade --run runs/crash02 --baseline runs/base02 --out reports/crash_public_02.md > /dev/null
grep -E "^\| ALL|applied —|lapsed|apply_conflicts" reports/crash_public_02.md | tee -a $LOG
