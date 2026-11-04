"""A股盘后事实采集与盘前预测冻结。仅使用可核对交易日的收盘K线。"""
import argparse
import hashlib
import json
import time
import urllib.parse
from datetime import datetime, time as clock, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .pipeline import ROOT, dump_json
from .sources import read_url, parse_rss

BJ = ZoneInfo("Asia/Shanghai")
SOURCE = "东方财富公开行情 API（非官方、可能延迟或限流）"
BASE = "https://push2.eastmoney.com/api/qt/"
SECTOR_FIELDS = "f12,f14,f3,f2"
STOCK_FIELDS = "f12,f13,f14,f3,f2"
BIAS_VALUES = {"positive", "negative", "mixed", "watch", "neutral"}

def data_path(root, folder, day):
    return root / "data" / folder / day[:4] / day[5:7] / (day + ".json")

def utc_now():
    return datetime.now(timezone.utc)

def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def as_utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return dt.astimezone(timezone.utc)

def freeze_forecast(day, root=ROOT, now=None):
    """晨间写入不可变预选股票池；开盘后禁止补冻或伪装历史预测。"""
    now = now or utc_now()
    local = now.astimezone(BJ)
    if local.date().isoformat() != day or local.time() >= clock(9, 30):
        return "outside_preopen_window"
    out = data_path(root, "forecasts", day)
    if out.exists():
        return "already_frozen"
    path = data_path(root, "analysis", day)
    if not path.exists():
        return "morning_analysis_missing"
    analysis = load_json(path)
    if analysis.get("report_date") != day or not analysis.get("a_share_sectors"):
        return "invalid_morning_analysis"
    generated = as_utc(analysis["generated_at_utc"])
    if generated > now or generated.astimezone(BJ).time() >= clock(9, 30):
        return "late_morning_analysis"
    watch = load_json(root / "config/sector_watchlist.json")
    forecast = {
        "schema_version": "1.0", "report_date": day,
        "frozen_at_utc": now.isoformat(), "forecast_generated_at_utc": analysis["generated_at_utc"],
        "analysis_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "a_share_bias": analysis.get("a_share_bias"),
        "a_share_sectors": analysis["a_share_sectors"],
        "a_share_outlook": analysis.get("a_share_outlook"),
        "watchlist": watch,
        "selection_rule": "每条盘前组合研判仅计一个评估样本，子板块及预选股不独立增加预测次数"
    }
    dump_json(out, forecast)
    return "frozen"

def json_api(endpoint, params):
    host = "https://push2his.eastmoney.com/api/qt/" if endpoint.startswith("stock/kline/") else BASE
    url = host + endpoint + "?" + urllib.parse.urlencode(params)
    raw = read_url(url, timeout=18)
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("接口返回缺失data: " + endpoint)
    return payload["data"]

def get_diff(data):
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    if not isinstance(diff, list):
        raise ValueError("invalid diff")
    return [x for x in diff if isinstance(x, dict)]

def list_sectors(kind, warnings):
    result = []
    size = 60
    for page in range(1, 16):
        try:
            data = json_api("clist/get", {
                "pn": page, "pz": size, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                "fid": "f3", "fs": "m:90+t:" + ("2" if kind == "industry" else "3") + "+f:!50",
                "fields": SECTOR_FIELDS
            })
            batch = get_diff(data)
            result.extend({"code": x.get("f12"), "name": x.get("f14"),
                           "change_pct_indicative": x.get("f3"), "kind": kind}
                          for x in batch if str(x.get("f12", "")).startswith("BK"))
            if not batch or len(result) >= int(data.get("total") or 0):
                break
            time.sleep(1)
        except Exception as exc:
            warnings.append(f"{kind} board list page {page}: {str(exc)[:160]}")
            break
    else:
        warnings.append(f"{kind} board list truncated at {len(result)}")
    return result

def close_bar(secid, day):
    """日K返回第一列必须是市场本地交易日期。不存在同日K线不准用旧价格。"""
    data = json_api("stock/kline/get", {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59",
        "klt": 101, "fqt": 0, "lmt": 5, "end": day.replace("-", "")
    })
    bars = []
    for line in data.get("klines") or []:
        columns = str(line).split(",")
        if len(columns) >= 3:
            try:
                bars.append((columns[0], float(columns[2])))
            except ValueError:
                pass
    if not bars or bars[-1][0] != day:
        raise ValueError(f"{secid} no same-day close; latest={bars[-1][0] if bars else 'none'}")
    if len(bars) < 2 or bars[-2][1] <= 0:
        raise ValueError(f"{secid} previous close unavailable")
    previous, close = bars[-2][1], bars[-1][1]
    if close <= 0:
        raise ValueError(f"{secid} invalid close")
    return {"market_date": day, "close": close, "reference_close": previous,
            "change_pct": round((close / previous - 1) * 100, 4),
            "value_kind": "daily_close", "source": SOURCE, "secid": secid}

def safe_bar(secid, day, warnings, label):
    try:
        result = close_bar(secid, day)
        return {"status": "ok", **result}
    except Exception as exc:
        warnings.append(f"{label}: {str(exc)[:170]}")
        return {"status": "unavailable", "change_pct": None, "market_date": None,
                "source": SOURCE, "secid": secid}

def find_tracks(forecast):
    out = []
    for entry in forecast.get("a_share_sectors", []):
        name = str(entry.get("sector", ""))
        matched = [t for t in forecast["watchlist"]["tracks"]
                   if any(term.lower() in name.lower() for term in t.get("terms", []))]
        out.append({"sector": name, "bias": entry.get("bias"), "reason": entry.get("reason"),
                    "tracks": matched})
    return out

def collect_news_clues(day, warnings):
    """仅作为未核验线索；盘中发生的事实必须由后续 GPT 独立查证。"""
    queries = ["A股 半导体 AI算力 存储 产业政策 when:1d", "中国 股票 经济 政策 盘中 when:1d"]
    begin = datetime.fromisoformat(day + "T09:30:00").replace(tzinfo=BJ).astimezone(timezone.utc)
    end = datetime.fromisoformat(day + "T15:00:00").replace(tzinfo=BJ).astimezone(timezone.utc)
    out, seen = [], set()
    for query in queries:
        try:
            params = urllib.parse.urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
            items = parse_rss(read_url("https://news.google.com/rss/search?" + params), "a_share")
            for event in items:
                timestamp = as_utc(event["published_at_utc"])
                if begin <= timestamp <= end and event["event_id"] not in seen:
                    out.append(event)
                    seen.add(event["event_id"])
        except Exception as exc:
            warnings.append("CN RSS: " + str(exc)[:160])
    return sorted(out, key=lambda x: x["published_at_utc"], reverse=True)[:20]

def collect_close(day, root=ROOT, now=None):
    now = now or utc_now()
    local = now.astimezone(BJ)
    if local.date().isoformat() != day or local.time() < clock(15, 30):
        return "not_collection_window"
    if local.weekday() >= 5:
        return "weekend"
    out = data_path(root, "close", day)
    if out.exists():
        return "already_collected"
    warnings = []
    benchmark = safe_bar("1.000300", day, warnings, "沪深300")
    if benchmark["status"] != "ok":
        return "benchmark_unavailable_or_market_closed: " + "; ".join(warnings)
    forecast_path = data_path(root, "forecasts", day)
    frozen = load_json(forecast_path) if forecast_path.exists() else None
    if frozen is None:
        warnings.append("没有开盘前冻结记录，禁止计算方向命中率")
    boards = list_sectors("industry", warnings) + list_sectors("concept", warnings)
    board_by_kind_name = {(b["kind"], b["name"]): b for b in boards}
    selected = find_tracks(frozen) if frozen else []
    observed_board_cache, stock_cache = {}, {}
    def board_price(board):
        key = board["code"]
        if key not in observed_board_cache:
            observed_board_cache[key] = safe_bar("90." + key, day, warnings, board["name"])
            time.sleep(0.2)
        return observed_board_cache[key]
    def stock_price(item):
        code, market, name = item
        key = market + "." + code
        if key not in stock_cache:
            stock_cache[key] = {"code": code, "name": name, "market": market,
                                **safe_bar(key, day, warnings, name)}
            time.sleep(0.2)
        return stock_cache[key]
    groups = []
    observed_keys = set()
    for entry in selected:
        components = []
        for track in entry["tracks"]:
            matches = [board_by_kind_name[(track["board_type"], alias)]
                       for alias in track["board_names"]
                       if (track["board_type"], alias) in board_by_kind_name]
            matched = matches[0] if matches else None
            quote = board_price(matched) if matched else {"status": "unavailable", "change_pct": None}
            component = {"key": track["key"], "name": track["name"],
                         "board_name": matched["name"] if matched else None,
                         "board_code": matched["code"] if matched else None,
                         "board_type": track["board_type"],
                         "is_proxy": bool(matched and matched["name"] != track["name"]),
                         "quote": quote, "stocks": [stock_price(s) for s in track["stocks"]]}
            components.append(component)
            if matched:
                observed_keys.add(matched["code"])
        eligible = bool(components) and all(
            x["quote"].get("status") == "ok" and not x["is_proxy"] for x in components)
        move = round(sum(x["quote"]["change_pct"] for x in components) / len(components), 4) if eligible else None
        bias = str(entry["bias"]).lower()
        hit = (move > 0 if bias == "positive" else move < 0) if eligible and move != 0 and bias in ("positive", "negative") else None
        groups.append({"sector": entry["sector"], "bias": bias, "reason": entry["reason"],
                       "components": components, "aggregated_change_pct": move,
                       "excess_vs_csi300_pct": round(move - benchmark["change_pct"], 4) if move is not None else None,
                       "direction_hit": hit, "evaluation": "directional" if hit is not None else "not_scorable"})
    hot = []
    for board in sorted(boards, key=lambda b: b["change_pct_indicative"] if isinstance(b["change_pct_indicative"], (int, float)) else -999, reverse=True):
        if board["code"] in observed_keys or len(hot) >= 5:
            continue
        quote = board_price(board)
        if quote.get("status") != "ok":
            continue
        hot_stocks = []
        try:
            data = json_api("clist/get", {"pn": 1, "pz": 6, "po": 1, "np": 1, "fltt": 2,
                            "invt": 2, "fid": "f3", "fs": "b:" + board["code"], "fields": STOCK_FIELDS})
            for row in get_diff(data):
                code, market = str(row.get("f12") or ""), str(row.get("f13") if row.get("f13") is not None else "")
                if len(code) == 6 and market in ("0", "1"):
                    hot_stocks.append(stock_price((code, market, str(row.get("f14") or code))))
                if len(hot_stocks) == 2:
                    break
        except Exception as exc:
            warnings.append(f"hot stocks {board['name']}: {str(exc)[:100]}")
        hot.append({"name": board["name"], "code": board["code"],
                    "board_type": board["kind"], "quote": quote,
                    "stocks": hot_stocks, "classification": "post_close_discovery"})
    result = {"schema_version": "1.0", "report_date": day, "market_date": day,
              "captured_at_utc": now.isoformat(), "source": SOURCE,
              "benchmark": {"name": "沪深300", "quote": benchmark},
              "forecast_sha256": hashlib.sha256(forecast_path.read_bytes()).hexdigest() if frozen else None,
              "forecast_frozen_at_utc": frozen.get("frozen_at_utc") if frozen else None,
              "forecast_generated_at_utc": frozen.get("forecast_generated_at_utc") if frozen else None,
              "predicted_groups": groups, "hot_sectors": hot,
              "news_clues": collect_news_clues(day, warnings), "warnings": warnings,
              "methodology": "仅对盘前冻结的方向性组合研判计分；组合内全部板块有同日原名指数才以等权涨幅比较绝对方向；代理指数、重点观察、混合和中性不计入命中率。"
             }
    dump_json(out, result)
    return "collected"

def render_close(root=ROOT):
    from .close_render import render_close_report, render_close_archive, render_close_home, validate_close_analysis
    snapshots = sorted((root / "data/close").glob("*/*/*.json"))
    ready = []
    for path in snapshots:
        day = path.stem
        analysis_path = data_path(root, "close_analysis", day)
        if not analysis_path.exists():
            continue
        raw, analysis = load_json(path), load_json(analysis_path)
        if raw.get("report_date") != day or analysis.get("report_date") != day:
            raise ValueError(f"date mismatch: {day}")
        validate_close_analysis(analysis)
        target = root / "reports/close" / day[:4] / day[5:7] / (day + ".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_close_report(raw, analysis, "../../../../"), encoding="utf-8")
        ready.append(day)
    folder = root / "reports/close"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "archive.html").write_text(render_close_archive(ready), encoding="utf-8")
    latest_raw = load_json(data_path(root, "close", max(ready))) if ready else None
    latest_analysis = load_json(data_path(root, "close_analysis", max(ready))) if ready else None
    (folder / "index.html").write_text(render_close_home(latest_raw, latest_analysis), encoding="utf-8")
    return ready

def check_release(day, root=ROOT):
    from .close_render import validate_close_analysis
    raw_path = data_path(root, "close", day)
    analysis_path = data_path(root, "close_analysis", day)
    html = root / "reports/close" / day[:4] / day[5:7] / (day + ".html")
    index = root / "reports/close/index.html"
    errors, warnings = [], []
    if not raw_path.exists(): errors.append("close snapshot missing")
    if not analysis_path.exists(): errors.append("verified close analysis missing")
    if not html.exists() or not index.exists(): errors.append("close HTML missing")
    if errors: return {"complete": False, "errors": errors, "warnings": warnings, "date": day}
    data, analysis = load_json(raw_path), load_json(analysis_path)
    try: validate_close_analysis(analysis)
    except ValueError as exc: errors.append(str(exc))
    if data.get("benchmark", {}).get("quote", {}).get("market_date") != day:
        errors.append("benchmark not same-day")
    if not data.get("forecast_sha256"):
        warnings.append("no preopen forecast freeze: do not calculate accuracy")
    if not any(x.get("aggregated_change_pct") is not None for x in data.get("predicted_groups", [])):
        warnings.append("no fully comparable forecast sector index")
    if not any(s.get("quote", {}).get("status") == "ok" for g in data.get("predicted_groups", []) for s in g.get("components", [])):
        warnings.append("no confirmed close quote for forecast sectors")
    if day not in html.read_text(encoding="utf-8") or day not in index.read_text(encoding="utf-8"):
        errors.append("HTML missing expected date")
    if analysis.get("summary", "") not in html.read_text(encoding="utf-8"):
        errors.append("analysis summary not found in HTML")
    warnings.extend(data.get("warnings", []))
    return {"complete": not errors and len(warnings) == 0, "published": not errors,
            "status": "FAILED" if errors else "DEGRADED" if warnings else "COMPLETE",
            "errors": errors, "warnings": warnings, "date": day,
            "directional_evaluable": sum(x.get("direction_hit") is not None for x in data.get("predicted_groups", [])),
            "directional_hits": sum(x.get("direction_hit") is True for x in data.get("predicted_groups", []))}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="Beijing market date; never enables historical recollection")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze-only", action="store_true")
    mode.add_argument("--collect-only", action="store_true")
    mode.add_argument("--render-only", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = p.parse_args()
    day = args.date or utc_now().astimezone(BJ).date().isoformat()
    datetime.strptime(day, "%Y-%m-%d")
    if args.freeze_only: print(freeze_forecast(day))
    elif args.collect_only: print(collect_close(day))
    elif args.render_only: print("rendered: " + str(render_close()))
    else:
        result = check_release(day)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("published", False): raise SystemExit(1)

if __name__ == "__main__":
    main()
