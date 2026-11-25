"""Write per-user macOS LaunchAgents for an existing GMR installation."""
from pathlib import Path
import plistlib

ROOT = Path(__file__).resolve().parent
DATA = Path.home() / "GMRData"
AGENTS = Path.home() / "Library" / "LaunchAgents"

def install():
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    AGENTS.mkdir(parents=True, exist_ok=True)
    programs = {
        "com.gmr.intraday": ("radar.py", "tick"),
        "com.gmr.intraday.awake": ("ops.py", "awake"),
        "com.gmr.intraday.web": ("ops.py", "web"),
        "com.gmr.intraday.sync": ("radar.py", "sync"),
    }
    for label, (script, action) in programs.items():
        path = AGENTS / f"{label}.plist"
        value = {
            "Label": label, "ProgramArguments": [str(ROOT / ".venv/bin/python"), str(ROOT / script), action],
            "WorkingDirectory": str(ROOT), "RunAtLoad": True, "Nice": 10, "LowPriorityIO": True,
            "ProcessType": "Background",
            "StandardOutPath": str(DATA / "logs/stdout.log"),
            "StandardErrorPath": str(DATA / "logs/stderr.log"),
            "EnvironmentVariables": {"GMR_DATA_DIR": str(DATA), "GMR_CONFIG": str(DATA / "watchlist.json"),
                "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        }
        if action == "web":
            value.update(KeepAlive=True, ThrottleInterval=30)
        else:
            value["StartInterval"] = 30 if action == "awake" else 60
        payload = plistlib.dumps(value)
        if not path.exists() or path.read_bytes() != payload:
            temp = path.with_suffix(".tmp")
            temp.write_bytes(payload)
            temp.replace(path)
        print(path)

if __name__ == "__main__":
    install()
