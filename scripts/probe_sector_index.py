"""Read-only QA of candidate GMR sector-index closing bars; no backtest mutations."""
import argparse
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .close_review import ROOT, safe_bar
from .pipeline import dump_json

def probe(day, root=ROOT):
    datetime.strptime(day, "%Y-%m-%d")
    warnings = []
    quote = safe_bar("90.BK0732", day, warnings, "东方财富贵金属 BK0732")
    verified = (quote.get("status") == "ok" and quote.get("market_date") == day
                and quote.get("secid") == "90.BK0732"
                and quote.get("close", 0) > 0 and quote.get("reference_close", 0) > 0)
    return {
        "report_date": day, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "prospective_index_source_validation_not_historical_forecast_scoring",
        "eastmoney_bk0732": {"index_name": "贵金属", "vendor": "东方财富",
                             "quote": quote, "verified_same_day_kline": bool(verified),
                             "source_url": "https://quote.eastmoney.com/bk/90.BK0732.html"},
        "ths_885530": {"index_name": "黄金概念", "vendor": "同花顺",
                        "identity_confirmed": True, "historical_daily_kline_qa": "not_integrated",
                        "source_url": "https://basic.10jqka.com.cn/885530/"},
        "ths_884215": {"index_name": "稀土", "vendor": "同花顺",
                        "identity_confirmed": True, "historical_daily_kline_qa": "not_integrated",
                        "source_url": "https://basic.10jqka.com.cn/884215/"},
        "warnings": warnings,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    a = p.parse_args()
    result = probe(a.date)
    destination = ROOT / "data/quality/sector_index_probe" / a.date[:4] / a.date[5:7] / (a.date + ".json")
    dump_json(destination, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
