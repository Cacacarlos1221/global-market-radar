#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
DATA="$HOME/GMRData"
PYTHON="$(printenv PYTHON || true)"
[[ -n "$PYTHON" ]] || PYTHON=python3
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p "$DATA/logs" "$HOME/Library/LaunchAgents"
if [[ ! -f "$DATA/watchlist.json" ]]; then
  cp watchlist.json "$DATA/watchlist.json"
fi
.venv/bin/python -m unittest discover -s tests -v
GMR_CONFIG="$DATA/watchlist.json" .venv/bin/python radar.py probe
.venv/bin/python deploy_agents.py
for label in com.gmr.intraday com.gmr.intraday.awake com.gmr.intraday.web com.gmr.intraday.sync; do
  if ! launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$label.plist"
  fi
done
echo "Installed per-user radar agents. The local web endpoint is http://127.0.0.1:18773/."
