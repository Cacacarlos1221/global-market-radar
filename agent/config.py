"""Minimal local .env loader: env vars take priority and credentials never print."""
import os
from pathlib import Path

def load_agent_env(path=None):
    source = Path(path) if path else Path(__file__).with_name(".env")
    if not source.exists():
        return False
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in ("MARKET_AGENT_BASE_URL", "MARKET_AGENT_MODEL", "MARKET_AGENT_API_KEY"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if value:
            os.environ.setdefault(key, value)
    return True
