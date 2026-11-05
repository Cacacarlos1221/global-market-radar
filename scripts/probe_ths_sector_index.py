"""One-off THS index K-line feasibility QA; never modify historical GMR results."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from .close_review import ROOT
from .pipeline import dump_json

def test_index(func, symbol, date):
    result = {"symbol": symbol, "interface": func.__name__,
              "status": "unavailable", "same_day_bar": False,
              "days": [], "last_quote": None}
    try:
        begin = (datetime.strptime(date, "%Y-%m-%d").date()).replace(day=1)
        df = func(symbol=symbol, start_date=begin.strftime("%Y%m%d"),
                  end_date=date.replace("-", ""))
        if df is None or len(df) == 0:
            raise ValueError("empty historical K-line response")
        rows = df.tail(8).to_dict(orient="records")
        dates = []
        for row in rows:
            value = row.get("日期", row.get("date", row.get("时间", "")))
            dates.append(str(value)[:10])
        result["days"] = dates
        result["same_day_bar"] = date in dates
        result["status"] = "ok" if result["same_day_bar"] else "stale_or_missing"
        result["last_quote"] = {str(k): str(v) for k,v in rows[-1].items()}
        result["columns"] = [str(c) for c in df.columns]
    except Exception as e:
        result["error"] = type(e).__name__ + ": " + str(e)[:350]
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-11-05")
    parser.add_argument("--root", type=Path, default=ROOT)
    a = parser.parse_args()
    d = {"report_date": a.date, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
         "probe_only_no_production_source_change": True}
    try:
        import akshare as ak
        d["akshare_version"] = getattr(ak, "__version__", "unknown")
        d["ths_884215_rare_industry"] = test_index(ak.stock_board_industry_index_ths, "稀土", a.date)
        d["ths_885530_gold_concept"] = test_index(ak.stock_board_concept_index_ths, "黄金概念", a.date)
    except Exception as e:
        d["import_error"] = type(e).__name__ + ": " + str(e)[:250]
    out = a.root / "data/quality/sector_index_probe" / a.date[:4] / a.date[5:7] / ("ths_" + a.date + ".json")
    dump_json(out, d)
    print(json.dumps(d, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
