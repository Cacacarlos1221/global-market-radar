"""Deterministic after-close facts-only safety net.

Never cites unverified RSS as researched news, never rewrites an authored review,
and never relies on a post-close selection to claim a prediction hit.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .close_review import ROOT, data_path, effective_close, load_json, usable_close_research
from .pipeline import dump_json

REPORT_TYPE = "GMR_deterministic_facts_only_fallback"
ANALYSIS_STATUS = "facts_only_pending_independent_research"

def fmt_pct(value):
    return (f"{value:+.2f}%" if isinstance(value, (float, int)) and not isinstance(value, bool)
            else "暂无同日行情")

def fmt_pp(value):
    return f"{value:+.2f}个百分点" if isinstance(value, (float, int)) else "—"

def valid_quote(quote, day):
    return (isinstance(quote, dict) and quote.get("status") == "ok"
            and quote.get("market_date") == day
            and isinstance(quote.get("change_pct"), (float, int))
            and not isinstance(quote.get("change_pct"), bool)
            and isinstance(quote.get("close"), (float, int))
            and isinstance(quote.get("reference_close"), (float, int))
            and quote["close"] > 0 and quote["reference_close"] > 0)

def factual_review(day, root=ROOT, clock=None):
    """Return a fact-only review strictly grounded in the existing same-day snapshot."""
    raw_path = data_path(root, "close", day)
    if not raw_path.exists():
        return None
    raw = effective_close(root, day)
    if raw.get("report_date") != day or raw.get("market_date") != day:
        return None
    bench = raw.get("benchmark", {}).get("quote", {})
    groups = raw.get("predicted_groups", [])
    hot = raw.get("hot_sectors", [])
    quotes = [bench]
    for group in groups:
        for c in group.get("components", []):
            quotes.append(c.get("quote", {}))
            quotes.extend(c.get("stocks", []))
    for board in hot:
        quotes.append(board.get("quote", {}))
    if not any(valid_quote(q, day) for q in quotes):
        return None
    now = (clock or datetime.now(timezone.utc)).astimezone(timezone.utc)
    benchmark_pct = bench.get("change_pct") if valid_quote(bench, day) else None
    directional = sum(g.get("bias") in ("positive", "negative") for g in groups)
    scored = [g for g in groups if isinstance(g.get("direction_hit"), bool)]
    hits = sum(g["direction_hit"] is True for g in scored)
    observed = sum(any(valid_quote(c.get("quote"), day) for c in g.get("components", [])) for g in groups)
    benchmark_text = ("沪深300收盘" + str(bench.get("close")) + "点，日涨跌" + fmt_pct(benchmark_pct)
                      if benchmark_pct is not None else "沪深300当天收盘行情仍缺失")
    summary = (
        f"GMR自动收盘事实版（非独立新闻研究，等待后续研究升级）。{day}已取得当日可核验行情；"
        f"{benchmark_text}。盘前跟踪共{len(groups)}组，有至少一项同日板块指数的{observed}组，"
        f"其中明确涨跌方向{directional}组、具备严格评分条件{len(scored)}组，"
        f"方向一致{hits}组。只有存在有效方向评分样本时这些数字才可用于计算命中率；"
        "未给出方向或仅有代理指数的主题不计严格命中率。"
        "以下仅逐项复述已封存的收盘K线事实，尚未核实独立新闻正文、发布时间与驱动因素，"
        "本事实版不作新闻归因或确定性因果解释。"
    )
    findings = [
        {"title": "当日收盘基准（源自同日行情）", "finding": benchmark_text, "source_ids": []},
        {"title": "盘前研判覆盖和方向评分分开统计",
         "finding": (f"冻结或预选关注{len(groups)}组，至少一项同日板块可观察{observed}组，"
                     f"明确方向{directional}组，严格可评分{len(scored)}组，其中方向一致{hits}组。"
                     "盘后新增热点不计入盘前评分，所有预测方向均以原始冻结为准。"),
         "source_ids": []},
    ]
    if hot:
        names = []
        for board in hot:
            if valid_quote(board.get("quote"), day):
                names.append(str(board.get("name", "未命名")) + fmt_pct(board["quote"]["change_pct"]))
        if names:
            findings.append({"title": "盘后筛选的热门板块（不计预测命中）",
                             "finding": "；".join(names[:5]) + "。这些仅是当天价格观察，不能用于倒推早晨预测。",
                             "source_ids": []})
    observations = []
    for group in groups:
        detail = []
        for component in group.get("components", []):
            quote = component.get("quote", {})
            if not valid_quote(quote, day):
                continue
            change = quote["change_pct"]
            label = str(component.get("board_name") or component.get("name") or "未知板块")
            proxy = "（已标注代理）" if component.get("is_proxy") else ""
            relative = (f"，相对沪深300{fmt_pp(change-benchmark_pct)}"
                        if benchmark_pct is not None else "，沪深300缺失，无法比较超额收益")
            stocks = [str(x.get("name", ""))+fmt_pct(x["change_pct"])
                      for x in component.get("stocks", []) if valid_quote(x, day)]
            detail.append(f"{label}{proxy} {fmt_pct(change)}{relative}" +
                          ("；固定跟踪股：" + "、".join(stocks[:8]) if stocks else ""))
        bias = str(group.get("bias") or "unknown")
        verdict = ("冻结方向一致" if group.get("direction_hit") is True else
                   "冻结方向偏离" if group.get("direction_hit") is False else
                   "没有可严格评分的明确方向结果")
        observations.append({
            "sector": str(group.get("sector") or "未命名主题"),
            "observation": (f"盘前标签{bias}；" + ("；".join(detail) if detail else "暂无有效同日板块指数")
                            + "；" + verdict + "。"),
            "explanation": ("仅为真实同日行情和冻结标签的机械对照；"
                            "尚未进行独立新闻核实，不能认定涨跌的原因，"
                            "不能将mixed/watch或代理主题事后改写为方向预测。"),
            "causal_status": "facts_only_not_researched", "source_ids": []
        })
    warnings = raw.get("warnings", [])
    next_watch = [
        "待GMR独立核验当日重大新闻正文、发布时间、公告与产业催化后，另行发布完整研究版。",
        "复核盘前明确方向覆盖率与严格可评分样本数量，不把代理主题或盘后热点当作命中。",
    ]
    if warnings:
        next_watch.append(f"本日行情存在{len(warnings)}条已记录质量或映射限制，逐项以原始行情异常清单为准。")
    return {
        "schema_version": "1.1", "report_date": day,
        "generated_at_utc": now.isoformat(), "report_type": REPORT_TYPE,
        "analysis_status": ANALYSIS_STATUS,
        "source_close_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "source_forecast_sha256": raw.get("forecast_sha256"),
        "source_revision_used": data_path(root, "close_revisions", day).exists(),
        "summary": summary, "key_findings": findings, "attributions": observations,
        "new_events": [], "news_sources": [], "next_watch": next_watch,
    }

def create_facts_fallback(day, root=ROOT, clock=None):
    """Keep facts and authored research in different files; never overwrite either."""
    authored_path = data_path(root, "close_analysis", day)
    fallback_path = data_path(root, "close_fact_analysis", day)
    if usable_close_research(root, day):
        return "independent_research_already_exists"
    if fallback_path.exists():
        return "facts_fallback_already_exists"
    result = factual_review(day, root, clock)
    if result is None:
        return "no_valid_same_day_close_facts"
    from .close_render import validate_close_analysis
    validate_close_analysis(result)
    dump_json(fallback_path, result)
    return "facts_fallback_created"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="Shanghai-local market date, YYYY-MM-DD")
    args = p.parse_args()
    from .close_review import BJ
    today = datetime.now(BJ).date().isoformat()
    day = args.date or today
    datetime.strptime(day, "%Y-%m-%d")
    status = create_facts_fallback(day)
    print(json.dumps({"date": day, "facts_fallback_status": status}, ensure_ascii=False))
    if status == "no_valid_same_day_close_facts":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
