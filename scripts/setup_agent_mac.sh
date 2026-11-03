#!/usr/bin/env bash
# Clone an isolated experiment into ~/Desktop/学习 and prepare an offline Python venv.
set -euo pipefail
REPO_URL="https://github.com/Cacacarlos1221/global-market-radar.git"
BRANCH="experiment/market-analysis-agent-v0"
DEST="$HOME/Desktop/学习/global-market-radar-agent"
mkdir -p "$(dirname "$DEST")"
command -v git >/dev/null || { echo "Git missing; run xcode-select --install"; exit 1; }
command -v python3 >/dev/null || { echo "Python 3.11+ required"; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if [ -e "$DEST" ] && [ ! -d "$DEST/.git" ]; then
  echo "Target directory exists but is not a git repository: $DEST"; exit 1
fi
if [ ! -d "$DEST/.git" ]; then
  git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$DEST"
else
  echo "Existing repository preserved; no automatic pull or overwrite."
fi
cd "$DEST"
if [ ! -f .venv/bin/python ]; then
  python3 -m venv .venv
fi
if [ ! -f agent/.env ]; then
  cp agent/.env.example agent/.env
  chmod 600 agent/.env
fi
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m agent.main doctor
if [ ! -f agent/output/2026-11-03/audit.json ]; then
  .venv/bin/python -m agent.main flow --date 2026-11-03 --offline
fi
echo "READY: $DEST"
echo "Model configuration: $DEST/agent/.env"
echo "Public research today: cd \"$DEST\" && .venv/bin/python -m agent.main research-official"
echo "GDELT research: .venv/bin/python -m agent.main research"
echo "After adding API credentials: .venv/bin/python -m agent.main smoke-model"
echo "Offline HTML: $DEST/agent/output/2026-11-03/report.preview.html"
