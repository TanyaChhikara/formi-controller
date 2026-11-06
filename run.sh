#!/usr/bin/env bash
# Starts the controller against a running simulator and runs until the scenario finishes.
# No Docker; needs Python 3.11+ with requirements.txt installed (httpx is the only runtime dependency).
# State goes to state/<scenario>.db (override with CONTROLLER_DB). Re-running resumes from it.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"
exec python -m controller.main --url "$SIM_URL"
