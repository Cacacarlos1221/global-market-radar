"""Recover only unavailable morning core quotes via timestamped, append-only supplements."""
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from .pipeline import ROOT
from .release_check import CORE
from .backfill_quote import backfill_quote

def recover(day=None, root=ROOT):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    day = day or today
    if day != today:
        raise ValueError("Cannot quietly repopulate historical snapshots")
    snapshot = root / "data/daily" / day[:4] / day[5:7] / (day + ".json")
    if not snapshot.exists():
        raise FileNotFoundError("Raw snapshot required before targeted backfill: " + str(snapshot))
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    if data.get("report_date") != day:
        raise ValueError("Snapshot report_date mismatch")
    quotes = {x.get("key"): x for x in data.get("quotes", [])}
    folder = root / "data/supplements" / day[:4] / day[5:7] / day
    result = {"report_date": day, "attempted": [], "recovered": [], "unavailable": [],
              "skipped": [], "errors": []}
    for key in CORE:
        if quotes.get(key, {}).get("status") == "ok":
            result["skipped"].append(key + ": original quote available")
            continue
        if (folder / (key + ".json")).exists():
            result["skipped"].append(key + ": already supplemented")
            continue
        result["attempted"].append(key)
        try:
            if backfill_quote(key, day, render=False):
                result["recovered"].append(key)
            else:
                result["unavailable"].append(key)
        except Exception as exc:
            result["unavailable"].append(key)
            result["errors"].append({"asset_key": key, "error": str(exc)[:240]})
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Current Beijing date YYYY-MM-DD")
    args = parser.parse_args()
    report = recover(args.date)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Transient quote failures are not fatal to report generation; retain errors.
    # The separate morning_audit returns DEGRADED rather than inventing prices.

if __name__ == "__main__":
    main()
