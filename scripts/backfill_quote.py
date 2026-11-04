"""Capture one missing quote for today's report, preserving the sealed snapshot.

This quote is collected at execution time, not retroactively as an 08:15 price.
"""
import argparse
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .pipeline import ROOT, QUOTE_COLS, append_unique, dump_json, render_all
from .sources import collect_quotes

def backfill_quote(asset_key="USD_CNY", report_date=None, *, render=True):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    date = report_date or today
    if date != today:
        raise ValueError("Only today's Beijing date is supported; not a historical as-of backfill")
    config = json.loads((ROOT / "config/instruments.json").read_text(encoding="utf-8"))
    selected = [x for x in config["assets"] if x["key"] == asset_key]
    if len(selected) != 1:
        raise ValueError(f"Unknown asset: {asset_key}")
    original_path = ROOT / "data/daily" / date[:4] / date[5:7] / f"{date}.json"
    if not original_path.exists():
        raise FileNotFoundError(f"Daily snapshot must exist: {original_path}")
    original = json.loads(original_path.read_text(encoding="utf-8"))
    if any(x.get("key") == asset_key and x.get("status") == "ok" for x in original["quotes"]):
        print(f"SKIP: {asset_key} already exists in original snapshot")
        return False
    path = ROOT / "data/supplements" / date[:4] / date[5:7] / date / f"{asset_key}.json"
    if path.exists():
        print(f"SKIP: supplement exists: {path}")
        return False
    quote = collect_quotes(selected)[0]
    if quote.get("status") != "ok" or quote.get("value") is None:
        raise RuntimeError(f"Quote unavailable; cannot fabricate: {quote.get('error')}")
    captured_at = datetime.now(timezone.utc).isoformat()
    dump_json(path, {
        "schema_version": "1.0", "report_date": date, "asset_key": asset_key,
        "base_snapshot_collected_at_utc": original["collected_at_utc"],
        "collected_at_utc": captured_at, "quote": quote,
        "note": "Supplement captured after original snapshot, not a historical as-of quote"
    })
    append_unique(ROOT / "data/history/quotes.csv", QUOTE_COLS,
                  [{"report_date": date, "asset_key": asset_key, **quote}],
                  ["report_date", "asset_key"])
    # Never publish a partial morning HTML before the verified AI analysis exists.
    if render:
        analysis_path = ROOT / "data/analysis" / date[:4] / date[5:7] / (date + ".json")
        if analysis_path.is_file():
            render_all()
        else:
            print("PENDING: verified analysis is missing; do not render an incomplete HTML")
    print(f"BACKFILLED {asset_key}={quote['value']} {quote['unit']} "
          f"quote_at={quote['observed_at_utc']} collected_at={captured_at}")
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", default="USD_CNY")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    backfill_quote(args.asset, args.date)

if __name__ == "__main__":
    main()
