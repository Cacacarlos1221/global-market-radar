#!/usr/bin/env bash
set -euo pipefail
REPO_URL="https://github.com/Cacacarlos1221/global-market-radar.git"
BRANCH="experiment/market-analysis-agent-v0"
DEST="$HOME/Desktop/学习/global-market-radar-agent"
mkdir -p "$(dirname "$DEST")"
if [ ! -d "$DEST/.git" ]; then
  command -v git >/dev/null || { echo "Please install git first (xcode-select --install)"; exit 1; }
  git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$DEST"
else
  echo "Existing repository kept; no automatic overwrite: $DEST"
fi
cd "$DEST"
command -v python3 >/dev/null || { echo "Please install Python 3.11+ first"; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
if [ ! -f agent/.env ]; then
  cp agent/.env.example agent/.env
  chmod 600 agent/.env
fi
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m agent.main plan --date 2026-11-03
echo
echo "Local folder: $DEST"
echo "Edit API credentials in: $DEST/agent/.env"
echo "Run offline: cd \"$DEST\" && .venv/bin/python -m agent.main flow --date 2026-11-03 --offline"
echo "Run web research: .venv/bin/python -m agent.main research --date 2026-11-03 --web"
echo "Run keycheck: .venv/bin/python -m agent.main keycheck"
