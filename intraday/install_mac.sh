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
PLIST="$HOME/Library/LaunchAgents/com.gmr.intraday.plist"
.venv/bin/python - "$PLIST" "$ROOT" "$DATA" <<'PY'
import plistlib,sys
from pathlib import Path
plist,root,data=map(Path,sys.argv[1:])
value={"Label":"com.gmr.intraday","ProgramArguments":[str(root/".venv/bin/python"),str(root/"radar.py"),"tick"],
"WorkingDirectory":str(root),"StartInterval":60,"RunAtLoad":True,"Nice":10,"LowPriorityIO":True,
"ProcessType":"Background","EnvironmentVariables":{"GMR_DATA_DIR":str(data),"GMR_CONFIG":str(data/"watchlist.json"),
"OMP_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","VECLIB_MAXIMUM_THREADS":"1","MKL_NUM_THREADS":"1",
"PATH":"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
"StandardOutPath":str(data/"logs/stdout.log"),"StandardErrorPath":str(data/"logs/stderr.log")}
with plist.open("wb") as f: plistlib.dump(value,f)
PY
launchctl bootout "gui/$(id -u)/com.gmr.intraday" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/com.gmr.intraday" | head -40 || true
echo "Installed. Active only on verified trading days; logged-in session required."
