#!/usr/bin/env bash
# Run one scenario end to end: baseline, sim, controller, grade.
#   scripts/run_scenario.sh scenarios/public_02_incidents.yaml 02 [port]
set -euo pipefail
cd "$(dirname "$0")/.."
SC=$1; NAME=$2; PORT=${3:-8700}
[ -d runs/base$NAME ] || python -m sim baseline --scenario "$SC" --run-dir runs/base$NAME
python -m sim serve --scenario "$SC" --run-dir runs/mine$NAME --force --port "$PORT" > /tmp/sim_$NAME.log 2>&1 &
SIM=$!
trap 'kill $SIM 2>/dev/null || true' EXIT
until grep -q ready /tmp/sim_$NAME.log; do
  kill -0 $SIM 2>/dev/null || { echo "simulator failed to start:"; cat /tmp/sim_$NAME.log; exit 1; }
  sleep 1
done
export CONTROLLER_DB=state/run_$NAME.db
rm -f $CONTROLLER_DB*
./run.sh http://127.0.0.1:$PORT
mkdir -p reports
python -m sim grade --run runs/mine$NAME --baseline runs/base$NAME --out reports/public_$NAME.md > /dev/null
sed -n '1,/## Governance/p' reports/public_$NAME.md
