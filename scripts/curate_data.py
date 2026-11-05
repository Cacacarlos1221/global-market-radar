"""Create complete corrected daily JSON and research CSV without changing raw records."""
import argparse
import csv
import hashlib
import json
import math
from datetime import date
from .pipeline import ROOT, dump_json, with_supplements

VERSION = "1.0"
CSV_COLUMNS = [
    "report_date", "asset_key", "symbol", "category", "unit", "market_date",
    "observed_at_utc", "available_at_utc", "value_kind", "value", "reference_close",
    "reference_date", "change_pct", "status", "quality_flags",
    "usable_for_price_analysis", "usable_for_return_analysis", "source",
    "source_url", "revision_kind", "revision_record", "raw_market_date",
    "raw_value", "raw_status", "raw_source", "raw_snapshot_sha256"
]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def valid_price(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0

def enrich(q, original, correction, supplement_path, day, collected, raw_hash, latest_cn):
    old = original.get(q["key"])
    flags = []
    if old is None:
        flags.append("missing_from_raw_snapshot")
    if correction:
        flags.append("source_corrected" if correction.get("kind") == "source_correction"
                     else "late_supplement")
    if not valid_price(q.get("value")):
        flags.append("invalid_or_missing_price")
    if q.get("status") != "ok":
        flags.append("source_status_" + str(q.get("status", "missing")))
    market_date = q.get("market_date")
    try:
        if not market_date or date.fromisoformat(market_date) > date.fromisoformat(day):
            flags.append("invalid_market_date")
    except (TypeError, ValueError):
        flags.append("invalid_market_date")
    if q.get("category") == "cn_index" and latest_cn and market_date and market_date < latest_cn:
        flags.append("stale_vs_cn_index_peer")
    if not valid_price(q.get("reference_close")) or not q.get("reference_date"):
        flags.append("missing_return_reference")
    if not isinstance(q.get("change_pct"), (int, float)) or not math.isfinite(q["change_pct"]):
        flags.append("missing_return_change")
    price_ok = q.get("status") == "ok" and not any(
        f in flags for f in ("invalid_or_missing_price", "invalid_market_date", "stale_vs_cn_index_peer")
    )
    return_ok = price_ok and "missing_return_reference" not in flags and "missing_return_change" not in flags
    enriched = dict(q)
    enriched.update({
        "available_at_utc": correction.get("collected_at_utc") if correction else collected if old else None,
        "quality_flags": flags,
        "usable_for_price_analysis": bool(price_ok),
        "usable_for_return_analysis": bool(return_ok),
        "revision_kind": ("source_correction" if correction and correction.get("kind") == "source_correction"
                          else "supplement" if correction else "none"),
        "revision_record": supplement_path if correction else None,
        "raw_market_date": old.get("market_date") if old else None,
        "raw_value": old.get("value") if old else None,
        "raw_status": old.get("status") if old else "missing",
        "raw_source": old.get("source") if old else None,
        "raw_snapshot_sha256": raw_hash
    })
    return enriched

def materialize_day(snapshot_path, root=ROOT):
    raw_bytes = snapshot_path.read_bytes()
    original = json.loads(raw_bytes)
    day = original["report_date"]
    if day != snapshot_path.stem:
        raise ValueError("Daily snapshot path and date are inconsistent")
    merged = with_supplements(original, root)
    folder = root / "data/supplements" / day[:4] / day[5:7] / day
    supplements, hashes = {}, {}
    if folder.exists():
        for p in sorted(folder.glob("*.json")):
            raw = p.read_bytes()
            supplements[p.stem] = json.loads(raw)
            hashes[p.stem] = digest(raw)
    raw_quotes = {q["key"]: q for q in original.get("quotes", [])}
    effective = {q["key"]: q for q in merged["quotes"]}
    instruments = json.loads((root / "config/instruments.json").read_text(encoding="utf-8"))["assets"]
    expected = {a["key"]: a for a in instruments}
    latest_cn = max((q["market_date"] for q in effective.values()
                     if q.get("category") == "cn_index" and q.get("status") == "ok"
                     and q.get("market_date")), default=None)
    quotes = []
    for key in list(expected) + [k for k in effective if k not in expected]:
        asset = expected.get(key, {})
        q = effective.get(key) or {
            "key": key, "symbol": asset.get("symbol"), "label": asset.get("label", key),
            "category": asset.get("category"), "unit": asset.get("unit"), "status": "missing",
            "value": None, "market_date": None, "observed_at_utc": None, "value_kind": None,
            "reference_close": None, "reference_date": None, "change_pct": None, "source": None
        }
        src = f"data/supplements/{day[:4]}/{day[5:7]}/{day}/{key}.json"
        quotes.append(enrich(q, raw_quotes, supplements.get(key), src,
                             day, original.get("collected_at_utc"), digest(raw_bytes), latest_cn))
    if len({q["key"] for q in quotes}) != len(quotes):
        raise ValueError("Duplicated asset keys in curated snapshot")
    return {
        "schema_version": VERSION, "dataset_type": "curated_daily_snapshot",
        "report_date": day, "report_timezone": original.get("report_timezone", "Asia/Shanghai"),
        "original_collected_at_utc": original.get("collected_at_utc"),
        "raw_snapshot_path": str(snapshot_path.relative_to(root)),
        "raw_snapshot_sha256": digest(raw_bytes), "supplement_sha256": hashes,
        "corrections_applied": merged.get("quote_revisions", []),
        "quotes": quotes, "news": original.get("news", []),
        "source_errors": original.get("source_errors", {}),
        "limitations": original.get("limitations", []),
        "methodology": "Deterministic raw+supplement overlay; use available_at_utc for as-of research."
    }

def csv_record(day, q):
    custom = {
        "report_date": day, "asset_key": q["key"],
        "quality_flags": "|".join(q["quality_flags"]),
        "usable_for_price_analysis": str(q["usable_for_price_analysis"]).lower(),
        "usable_for_return_analysis": str(q["usable_for_return_analysis"]).lower()
    }
    return {k: custom.get(k, q.get(k)) for k in CSV_COLUMNS}

def build(root=ROOT):
    snapshots = sorted((root / "data/daily").glob("*/*/*.json"))
    if not snapshots:
        raise ValueError("No source snapshots exist")
    days = [materialize_day(p, root) for p in snapshots]
    rows = [csv_record(d["report_date"], q) for d in days for q in d["quotes"]]
    if len({(r["report_date"], r["asset_key"]) for r in rows}) != len(rows):
        raise ValueError("Duplicate report_date / asset_key in curated CSV")
    base = root / "data/curated"
    for data in days:
        day = data["report_date"]
        dump_json(base / "daily" / day[:4] / day[5:7] / (day + ".json"), data)
    destination = base / "history/quotes.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows({k: "" if r[k] is None else r[k] for k in CSV_COLUMNS} for r in rows)
    manifest = {
        "schema_version": VERSION, "dataset_type": "curated_history_manifest",
        "report_dates": [d["report_date"] for d in days],
        "daily_files": len(days), "quote_rows": len(rows),
        "source_corrected_rows": sum(q["revision_kind"] == "source_correction"
                                     for d in days for q in d["quotes"]),
        "supplemented_rows": sum(q["revision_kind"] == "supplement" for d in days for q in d["quotes"]),
        "price_usable_rows": sum(q["usable_for_price_analysis"] for d in days for q in d["quotes"]),
        "return_usable_rows": sum(q["usable_for_return_analysis"] for d in days for q in d["quotes"]),
        "history_csv": "data/curated/history/quotes.csv",
        "primary_key": ["report_date", "asset_key"],
        "raw_history_unchanged": True
    }
    dump_json(base / "manifest.json", manifest)
    return manifest

def main():
    parser = argparse.ArgumentParser(description="Build corrected daily JSON and history CSV")
    parser.parse_args()
    print(json.dumps(build(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
