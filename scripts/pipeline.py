"""Daily fact collection, lossless snapshots, CSV ledgers and static HTML rendering."""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .sources import collect_news, collect_quotes
from .render import render_archive, render_report, pending_home

ROOT = Path(__file__).resolve().parents[1]
QUOTE_COLS = ["report_date", "asset_key", "symbol", "category", "unit", "market_date",
              "observed_at_utc", "value_kind", "value", "reference_close",
              "reference_date", "change_pct", "status", "source"]
EVENT_COLS = ["report_date", "event_id", "topic", "published_at_utc",
              "headline", "source", "url", "verification"]

def dump_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def append_unique(path, columns, rows, unique_keys):
    path.parent.mkdir(parents=True, exist_ok=True)
    old = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            old = list(csv.DictReader(fh))
    existing = {tuple(row.get(key) for key in unique_keys) for row in old}
    for row in rows:
        token = tuple(str(row.get(key, "")) for key in unique_keys)
        if token not in existing:
            old.append({k: "" if row.get(k) is None else str(row.get(k)) for k in columns})
            existing.add(token)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(old)

def collect(report_date):
    settings = json.loads((ROOT / "config/instruments.json").read_text(encoding="utf-8"))
    quotes = collect_quotes(settings["assets"])
    events, news_errors = collect_news()
    daily = {
        "schema_version": "1.0", "report_date": report_date,
        "report_timezone": settings["timezone"],
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "quotes": quotes, "news": events,
        "source_errors": {"news": news_errors},
        "limitations": [
            "Yahoo Finance chart API unofficial: quotes may be delayed or unavailable",
            "RSS headlines are not independently fact checked",
            "Quote change uses the previous available daily bar, not necessarily yesterday calendar day"
        ]
    }
    out = ROOT / "data/daily" / report_date[:4] / report_date[5:7] / (report_date + ".json")
    if out.exists():
        raise FileExistsError(f"Snapshot already exists, not overwritten: {out}")
    dump_json(out, daily)
    quote_rows = [{"report_date": report_date, "asset_key": q["key"], **q} for q in quotes]
    event_rows = [{"report_date": report_date, **e} for e in events]
    append_unique(ROOT / "data/history/quotes.csv", QUOTE_COLS, quote_rows, ["report_date", "asset_key"])
    append_unique(ROOT / "data/history/events.csv", EVENT_COLS, event_rows, ["report_date", "event_id"])
    return daily

def render_all():
    snapshots = sorted((ROOT / "data/daily").glob("*/*/*.json"))
    dates = []
    for path in snapshots:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            date = data["report_date"]
            if date != path.stem:
                raise ValueError("report_date must match snapshot filename")
            a_path = ROOT / "data/analysis" / date[:4] / date[5:7] / (date + ".json")
            analysis = json.loads(a_path.read_text(encoding="utf-8")) if a_path.exists() else None
            if analysis is not None and analysis.get("report_date") != date:
                raise ValueError(f"analysis report_date mismatch: {a_path}")
            report_path = ROOT / "reports" / date[:4] / date[5:7] / (date + ".html")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(render_report(data, analysis, "../../../index.html"), encoding="utf-8")
            dates.append(date)
        except Exception as exc:
            raise RuntimeError(f"Could not render {path}: {exc}") from exc
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/archive.html").write_text(render_archive(dates), encoding="utf-8")
    if dates:
        latest = max(dates)
        index = ROOT / "data/daily" / latest[:4] / latest[5:7] / (latest + ".json")
        a_path = ROOT / "data/analysis" / latest[:4] / latest[5:7] / (latest + ".json")
        analysis = json.loads(a_path.read_text(encoding="utf-8")) if a_path.exists() else None
        (ROOT / "index.html").write_text(
            render_report(json.loads(index.read_text(encoding="utf-8")), analysis, "reports/archive.html"),
            encoding="utf-8")
    else:
        (ROOT / "index.html").write_text(pending_home(), encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Beijing report date, YYYY-MM-DD")
    parser.add_argument("--render-only", action="store_true", help="No network, render snapshots and analyses")
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    date = args.date or today
    datetime.strptime(date, "%Y-%m-%d")
    if not args.render_only:
        try:
            collect(date)
        except FileExistsError as exc:
            print(f"SKIP: {exc}")
    render_all()
    print(f"Done: {date}; render_only={args.render_only}")

if __name__ == "__main__":
    main()
