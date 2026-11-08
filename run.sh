#!/usr/bin/env bash
# Starts the controller against a running simulator and runs until the scenario finishes. No manual steps.
#   ./run.sh http://127.0.0.1:8700
# No Docker: plain Python 3.10+ (tested on 3.13 Linux and 3.12 macOS). The only runtime dependency is httpx.
# On first run this creates a private virtualenv in .venv/ and installs requirements.txt into it.
# State goes to state/<scenario>.db (override with CONTROLLER_DB). Re-running against the same world resumes.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"

# pick a Python >= 3.10 (some boxes only have `python3`, some have several)
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "run.sh: need Python 3.10+ on PATH" >&2; exit 1; }

# dependencies: use them if already importable, else install into .venv once
if ! "$PY" -c 'import httpx' >/dev/null 2>&1; then
  if [ ! -x .venv/bin/python ]; then
    "$PY" -m venv .venv
  fi
  .venv/bin/python -m pip install -q -r requirements.txt
  PY=.venv/bin/python
fi

exec "$PY" -m controller.main --url "$SIM_URL"
