"""Reject incomplete daily HTML before treating a morning report as published."""
import argparse
import json
from datetime import datetime
from html import escape
from pathlib import Path
from .pipeline import ROOT, with_supplements
from .render import validate_analysis

CORE = ("USD_CNY", "AUD_CNY", "NASDAQ", "SP500", "DOW", "AUD_USD")
SECTIONS = ("01 / 关键市场数据", "02 / 全量监测指标",
            "03 / 昨夜市场走势与原因", "04 / 国际重要新闻综述",
            "05 / A股开盘前研判", "06 / 新闻来源与参考资料")

def verify(date, root=ROOT):
    """Verify local repo artifacts; external Pages deployment must be checked separately."""
    datetime.strptime(date, "%Y-%m-%d")
    parts = (date[:4], date[5:7])
    snap = root.joinpath("data", "daily", *parts, date + ".json")
    analysis_path = root.joinpath("data", "analysis", *parts, date + ".json")
    html_path = root.joinpath("reports", *parts, date + ".html")
    index = root / "index.html"
    errors, warnings = [], []
    if not snap.exists():
        errors.append(f"Missing snapshot: {snap}")
    if not analysis_path.exists():
        errors.append(f"Missing analysis: {analysis_path}")
    if errors:
        return {"date": date, "complete": False, "errors": errors, "warnings": warnings}
    data = with_supplements(json.loads(snap.read_text(encoding="utf-8")), root)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    if data.get("report_date") != date or analysis.get("report_date") != date:
        errors.append("report_date inconsistent")
    try:
        validate_analysis(analysis)
    except ValueError as exc:
        errors.append("Invalid analysis references: " + str(exc))
    if not isinstance(analysis.get("market_summary"), str) or not analysis["market_summary"].strip():
        errors.append("market_summary empty")
    if not isinstance(analysis.get("a_share_outlook"), str) or not analysis["a_share_outlook"].strip():
        errors.append("a_share_outlook empty")
    digest = analysis.get("news_digest") or {}
    if not isinstance(digest, dict) or not digest.get("overview") or not digest.get("items"):
        errors.append("verified news digest missing (cannot call this a full analyzed report)")
    present = {q.get("key"): q for q in data.get("quotes", [])}
    for key in CORE:
        q = present.get(key)
        if not q:
            errors.append(f"Missing core asset {key}")
        elif q.get("status") != "ok":
            warnings.append(f"{key} quote unavailable")
    if not html_path.exists() or not index.exists():
        errors.append("HTML index or dated report missing")
    else:
        html = html_path.read_text(encoding="utf-8")
        latest = index.read_text(encoding="utf-8")
        for name, body in (("dated", html), ("index", latest)):
            if "全球市场晨报 · " + date not in body or "完整分析版" not in body:
                errors.append(f"{name} not fully analyzed for report date")
            for section in SECTIONS:
                if section not in body:
                    errors.append(f"{name} missing section: {section}")
            if escape(analysis["market_summary"]) not in body:
                errors.append(f"{name} market summary does not match analysis JSON")
        for item in digest.get("items", []):
            for ref in item.get("source_ids", []):
                if f'href="#ref-{escape(ref)}"' not in html:
                    errors.append(f"Missing news citation link: {ref}")
    return {"date": date, "complete": not errors, "errors": errors, "warnings": warnings,
            "assets": len(data.get("quotes", [])), "stories": len(digest.get("items", []))}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Beijing report date YYYY-MM-DD")
    args = parser.parse_args()
    result = verify(args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["complete"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
