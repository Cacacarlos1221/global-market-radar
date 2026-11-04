"""GMR morning delivery auditor. Report and forecast validations are deliberately separate."""
import argparse
import hashlib
import json
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .pipeline import ROOT
from .release_check import CORE, verify

BJ = ZoneInfo("Asia/Shanghai")

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def parsed_utc(value):
    if not isinstance(value, str):
        raise ValueError("timezone-aware timestamp required")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp missing timezone")
    return dt.astimezone(timezone.utc)

def audit(day, root=ROOT, now=None):
    """Produce machine-readable, evidence-based morning acceptance results."""
    datetime.strptime(day, "%Y-%m-%d")
    now = now or datetime.now(timezone.utc)
    parts = (day[:4], day[5:7], day + ".json")
    snapshot = root.joinpath("data", "daily", *parts)
    analysis = root.joinpath("data", "analysis", *parts)
    forecast = root.joinpath("data", "forecasts", *parts)
    result = {
        "report_date": day, "checked_at_utc": now.isoformat(),
        "snapshot_present": snapshot.is_file(), "analysis_present": analysis.is_file(),
        "report_published": False, "report_status": "FAILED",
        "forecast_state": "MISSING", "forecast_eligible_for_scoring": False,
        "errors": [], "warnings": [], "quotes": {}, "release": None
    }
    if snapshot.is_file():
        data = read_json(snapshot)
        if data.get("report_date") != day:
            result["errors"].append("snapshot report_date mismatch")
        if not data.get("collected_at_utc"):
            result["warnings"].append("no snapshot collected_at_utc provenance")
        mapping = {q.get("key"): q for q in data.get("quotes", [])}
        for key in CORE:
            q = mapping.get(key, {})
            result["quotes"][key] = {
                "status": q.get("status", "missing"),
                "market_date": q.get("market_date"),
                "source": q.get("source"),
                "observed_at_utc": q.get("observed_at_utc")
            }
            if q.get("status") != "ok":
                result["warnings"].append(key + " unavailable")
    else:
        result["errors"].append("today raw snapshot absent")
    if analysis.is_file():
        content = read_json(analysis)
        if content.get("report_date") != day:
            result["errors"].append("analysis report_date mismatch")
        try:
            created = parsed_utc(content.get("generated_at_utc"))
            local = created.astimezone(BJ)
            if local.date().isoformat() != day or local.time() >= time(9, 30):
                result["warnings"].append("analysis not generated before local market open")
            if created > now:
                result["errors"].append("analysis timestamp in the future")
        except (TypeError, ValueError) as exc:
            result["errors"].append("invalid analysis generated_at_utc: " + str(exc))
    else:
        result["errors"].append("today verified AI analysis absent")
    if forecast.is_file():
        frozen = read_json(forecast)
        try:
            created = parsed_utc(frozen["frozen_at_utc"]).astimezone(BJ)
            if created.date().isoformat() != day or created.time() >= time(9, 30):
                result["forecast_state"] = "INVALID_FREEZE_TIME"
            elif analysis.is_file() and hashlib.sha256(analysis.read_bytes()).hexdigest() != frozen.get("analysis_sha256"):
                result["forecast_state"] = "MISMATCH_ANALYSIS_HASH"
            elif frozen.get("report_date") != day:
                result["forecast_state"] = "INVALID_REPORT_DATE"
            elif not frozen.get("a_share_sectors"):
                result["forecast_state"] = "EMPTY"
            else:
                result["forecast_state"] = "FROZEN"
                result["forecast_eligible_for_scoring"] = True
        except (KeyError, TypeError, ValueError):
            result["forecast_state"] = "INVALID"
        if not result["forecast_eligible_for_scoring"]:
            result["warnings"].append("invalid or inconsistent pre-open forecast, must not score")
    else:
        result["warnings"].append("no pre-open forecast freeze; do not score, but keep report independent")
    if snapshot.is_file() and analysis.is_file():
        try:
            check = verify(day, root)
            result["release"] = check
            result["report_published"] = check["complete"]
            result["warnings"].extend(check.get("warnings", []))
            if not check["complete"]:
                result["errors"].extend(check.get("errors", []))
        except (OSError, TypeError, ValueError, KeyError) as exc:
            result["errors"].append("release_check raised: " + str(exc)[:300])
    # Freeze status must not block publication: it has a separate scoring contract.
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["errors"] = list(dict.fromkeys(result["errors"]))
    result["report_status"] = ("FAILED" if not result["report_published"] or result["errors"]
                               else "DEGRADED" if any(
                                   "unavailable" in w or "not generated before" in w
                                   for w in result["warnings"]) else "COMPLETE")
    result["pages_http_verified"] = False  # Local audit cannot verify external Pages.
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Beijing YYYY-MM-DD")
    parser.add_argument("--require-published", action="store_true")
    args = parser.parse_args()
    report = audit(args.date)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_published and not report["report_published"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
