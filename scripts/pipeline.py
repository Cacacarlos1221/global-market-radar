"""Daily fact collection, lossless snapshots, CSV ledgers and static HTML rendering."""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .sources import collect_news, collect_quotes
from .render import render_archive, render_report, pending_home, validate_analysis

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

def with_supplements(snapshot, root=ROOT):
    """Overlay supplemental quotes without mutating the original snapshot."""
    data = dict(snapshot)
    data["quotes"] = [dict(x) for x in snapshot.get("quotes", [])]
    data["supplements"] = []
    data["quote_revisions"] = []
    date = data["report_date"]
    folder = root / "data/supplements" / date[:4] / date[5:7] / date
    if not folder.exists():
        return data
    for path in sorted(folder.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        quote = record.get("quote") or {}
        if record.get("report_date") != date or quote.get("key") != path.stem or quote.get("status") != "ok":
            raise ValueError(f"Malformed quote supplement: {path}")
        if not record.get("collected_at_utc") or quote.get("value") is None:
            raise ValueError(f"Missing supplement provenance: {path}")
        value = dict(quote)
        value["supplement_collected_at_utc"] = record["collected_at_utc"]
        existing = {x["key"]: i for i, x in enumerate(data["quotes"])}
        if value["key"] in existing:
            original = data["quotes"][existing[value["key"]]]
            if original.get("status") == "ok":
                if record.get("kind") != "source_correction":
                    raise ValueError(f"Supplement would overwrite a valid quote: {path}")
                source_url = record.get("source_url", "")
                old_date = original.get("market_date") or ""
                new_date = value.get("market_date") or ""
                if not (source_url.startswith("https://") and old_date < new_date <= date):
                    raise ValueError(f"Source correction must cite evidence and a newer market date: {path}")
                if value.get("source_url") != source_url:
                    raise ValueError(f"Source URL mismatch in correction: {path}")
                value["correction_note"] = "数据源滞后，采用可核实来源修正"
                data["quote_revisions"].append({
                    "key": value["key"], "old_market_date": old_date,
                    "old_value": original["value"], "new_market_date": new_date,
                    "new_value": value["value"], "source_url": source_url,
                    "corrected_at_utc": record["collected_at_utc"]
                })
            data["quotes"][existing[value["key"]]] = value
        elif value["key"] == "USD_CNY":
            data["quotes"].insert(0, value)
        else:
            data["quotes"].append(value)
        data["supplements"].append({"key": value["key"], "collected_at_utc": record["collected_at_utc"]})
    return data

def render_all():
    snapshots = sorted((ROOT / "data/daily").glob("*/*/*.json"))
    dates = []
    for path in snapshots:
        try:
            data = with_supplements(json.loads(path.read_text(encoding="utf-8")))
            date = data["report_date"]
            if date != path.stem:
                raise ValueError("report_date must match snapshot filename")
            a_path = ROOT / "data/analysis" / date[:4] / date[5:7] / (date + ".json")
            analysis = json.loads(a_path.read_text(encoding="utf-8")) if a_path.exists() else None
            if analysis is not None and analysis.get("report_date") != date:
                raise ValueError(f"analysis report_date mismatch: {a_path}")
            if analysis is not None:
                validate_analysis(analysis)
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
            render_report(with_supplements(json.loads(index.read_text(encoding="utf-8"))), analysis, "reports/archive.html"),
            encoding="utf-8")
    else:
        (ROOT / "index.html").write_text(pending_home(), encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Beijing report date, YYYY-MM-DD")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--render-only", action="store_true", help="No network, render snapshots and analyses")
    mode.add_argument("--collect-only", action="store_true", help="Collect facts without publishing a partial HTML report")
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    date = args.date or today
    datetime.strptime(date, "%Y-%m-%d")
    if not args.render_only:
        try:
            collect(date)
        except FileExistsError as exc:
            print(f"SKIP: {exc}")
    if not args.collect_only:
        render_all()
    print(f"Done: {date}; render_only={args.render_only}; collect_only={args.collect_only}")

if __name__ == "__main__":
    main()
