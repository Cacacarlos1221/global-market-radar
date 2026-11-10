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

def approved_watchlist(root, day, now):
    """Apply only user-confirmed sector tracks with a strictly future effective day."""
    watch = load_json(root / "config/sector_watchlist.json")
    registry_path = root / "config/sector_index_registry.json"
    if not registry_path.exists():
        return watch, [], None
    registry = load_json(registry_path)
    tracks = list(watch.get("tracks", []))
    applied = []
    for decision in registry.get("approved", []):
        if decision.get("status") != "approved":
            continue
        try:
            approved_at = as_utc(decision["approved_at_utc"])
            effective = datetime.strptime(decision["effective_from"], "%Y-%m-%d").date()
            track = decision["track"]
            if (approved_at > now or effective <= approved_at.astimezone(BJ).date()
                    or effective.isoformat() > day):
                continue
            if not (track.get("key") and track.get("name")
                    and track.get("board_type") in ("industry", "concept")
                    and isinstance(track.get("board_names"), list)
                    and all(isinstance(name, str) and name for name in track["board_names"])
                    and track["board_names"]):
                continue
            tracks = [x for x in tracks if x.get("key") != track["key"]]
            new_track = {
                "key": track["key"], "name": track["name"],
                "terms": list(track.get("terms", [track["name"]])),
                "board_names": list(track["board_names"]), "board_type": track["board_type"],
                "stocks": list(track.get("stocks", [])), "user_approved": True,
                "mapping_relation": track.get("mapping_relation", "exact")
            }
            code = str(track.get("board_code") or "")
            if code.startswith("BK") and code[2:].isdigit():
                new_track["board_code"] = code
                new_track["board_name"] = str(track.get("board_name") or track["board_names"][0])
            tracks.append(new_track)
            applied.append({"topic": decision.get("topic", track["name"]),
                            "key": track["key"], "effective_from": decision["effective_from"],
                            "approved_at_utc": decision["approved_at_utc"],
                            "mapping_relation": track.get("mapping_relation", "exact"),
                            "approved_scope": decision.get("approved_scope")})
        except (KeyError, TypeError, ValueError):
            continue
    watch["tracks"] = tracks
    return watch, applied, hashlib.sha256(registry_path.read_bytes()).hexdigest()

def freeze_forecast(day, root=ROOT, now=None):
    """晨间写入不可变预选股票池；开盘后禁止补冻或伪装历史预测。"""
    now = now or utc_now()
    local = now.astimezone(BJ)
    if local.date().isoformat() != day or local.time() >= clock(9, 30):
        return "outside_preopen_window"
    # Weekend reports are informational only: never create a scorable A-share forecast.
    if local.weekday() >= 5:
        return "non_trading_day"
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
    watch, mapping_decisions, mapping_sha = approved_watchlist(root, day, now)
    forecast = {
        "schema_version": "1.0", "report_date": day,
        "frozen_at_utc": now.isoformat(), "forecast_generated_at_utc": analysis["generated_at_utc"],
        "analysis_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "a_share_bias": analysis.get("a_share_bias"),
        "a_share_sectors": analysis["a_share_sectors"],
        "a_share_outlook": analysis.get("a_share_outlook"),
        "watchlist": watch,
        "sector_mapping_approvals_applied": mapping_decisions,
        "sector_mapping_registry_sha256": mapping_sha,
        "selection_rule": "每条盘前组合研判仅计一个评估样本，子板块及预选股不独立增加预测次数",
        "unconfigured_sector_policy": "仅允许依原始晨报板块全名，在行业板块和概念板块中进行完全同名的确定性匹配，绝不追涨挑选近义词"
    }
    dump_json(out, forecast)
    return "frozen"

API_LAST_REQUEST = 0.0
# Public price endpoints may hang; the after-close workflow has a 26 minute job timeout.
# Keep per-call waits bounded and prefer a flagged partial snapshot over losing the whole run.
API_TIMEOUT_SECONDS = 7
MAX_COLLECTION_SECONDS = 480

def json_api(endpoint, params):
    """Rate-limit public quotes; fail over across documented board-list endpoints."""
    global API_LAST_REQUEST
    params = dict(params)
    kline = endpoint.startswith("stock/kline/")
    board_list = endpoint == "clist/get" and str(params.get("fs", "")).startswith("m:90+t:")
    if board_list:
        params.setdefault("ut", "bd1d9ddb04089700cf9c27f6f7426281")
        board_host = ("17.push2.eastmoney.com" if "+t:2" in params["fs"] else
                      "79.push2.eastmoney.com" if "+t:3" in params["fs"] else
                      "push2.eastmoney.com")
        hosts = [BASE, "https://push2delay.eastmoney.com/api/qt/",
                 "https://" + board_host + "/api/qt/"]
    else:
        hosts = ["https://push2his.eastmoney.com/api/qt/" if kline else BASE]
    last_error = None
    for host in dict.fromkeys(hosts):
        url = host + endpoint + "?" + urllib.parse.urlencode(params)
        for attempt in range(1 if board_list else 2):
            pause = 1.1 - (time.monotonic() - API_LAST_REQUEST)
            if pause > 0:
                time.sleep(pause)
            API_LAST_REQUEST = time.monotonic()
            try:
                raw = read_url(url, timeout=API_TIMEOUT_SECONDS)
                payload = json.loads(raw.decode("utf-8-sig"))
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, dict):
                    raise ValueError("接口返回缺失data: " + endpoint)
                if board_list and int(params.get("pn", 1)) == 1 and not data.get("diff"):
                    raise ValueError("板块排行接口返回空列表")
                return data
            except Exception as exc:
                last_error = exc
                if attempt == 0 and not board_list:
                    time.sleep(1)
        if board_list:
            print(f"GMR_CLOSE board-list host fallback after {host}: {str(last_error)[:110]}", flush=True)
    raise RuntimeError("Eastmoney API unavailable: " + str(last_error)[:180])

def get_diff(data):
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    if not isinstance(diff, list):
        raise ValueError("invalid diff")
    return [x for x in diff if isinstance(x, dict)]

def list_sectors(kind, warnings):
    result = []
    # Top 120 from each category is ample for observed Top-5; preselected
    # themes outside the ranking sample use historical verified board identities.
    size = 40
    for page in range(1, 4):
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
            time.sleep(0.2)
        except Exception as exc:
            warnings.append(f"{kind} board list page {page}: {str(exc)[:160]}")
            break
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

def yahoo_benchmark_fallback(day, warnings):
    """Use CSI300 Yahoo daily bars only when Eastmoney benchmark is unavailable."""
    from .sources import yahoo_chart, parse_bars
    try:
        bars = parse_bars(yahoo_chart("000300.SS", "1d", "14d"))
        if len(bars) < 2 or bars[-1]["market_date"] != day:
            raise ValueError("Yahoo benchmark has no same-day close")
        previous, close = bars[-2]["value"], bars[-1]["value"]
        if previous <= 0 or close <= 0:
            raise ValueError("Yahoo benchmark missing valid prices")
        return {"status": "ok", "market_date": day, "close": close,
                "reference_close": previous, "change_pct": round((close / previous - 1) * 100, 4),
                "value_kind": "daily_close", "source": "Yahoo Finance chart API (unofficial)",
                "secid": "000300.SS"}
    except Exception as exc:
        warnings.append("Yahoo CSI300 fallback: " + str(exc)[:170])
        return {"status": "unavailable", "change_pct": None, "market_date": None,
                "source": "Yahoo Finance chart API (unofficial)", "secid": "000300.SS"}

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

def observation_plan(day, root, frozen):
    """A missing freeze disables statistical scoring, never collection or the daily review."""
    if frozen:
        return frozen, "frozen", None
    watchlist = load_json(root / "config/sector_watchlist.json")
    morning_path = data_path(root, "analysis", day)
    if morning_path.exists():
        morning = load_json(morning_path)
        if morning.get("report_date") == day and isinstance(morning.get("a_share_sectors"), list):
            generated = morning.get("generated_at_utc")
            try:
                early = as_utc(generated).astimezone(BJ)
                if early.date().isoformat() == day and early.time() < clock(9, 30):
                    return {"a_share_sectors": morning["a_share_sectors"], "watchlist": watchlist}, \
                        "morning_analysis_unfrozen", hashlib.sha256(morning_path.read_bytes()).hexdigest()
            except (ValueError, TypeError, AttributeError):
                pass
    return {
        "a_share_sectors": [
            {"sector": track["name"], "bias": "watch", "reason": "默认固定观察池；非当天预测"}
            for track in watchlist["tracks"]
        ], "watchlist": watchlist
    }, "watchlist_only", None

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

def historical_board_catalog(root, day):
    """Reuse only previously verified vendor board identities, never old quote values."""
    history = sorted(p for p in (root / "data/close").glob("*/*/*.json") if p.stem < day)
    catalog = {}
    for p in history[-30:]:
        snap = load_json(p)
        entries = []
        for group in snap.get("predicted_groups", []):
            entries.extend(group.get("components", []))
        for item in entries:
            kind, code, name = item.get("board_type"), item.get("board_code"), item.get("board_name")
            if kind in ("industry", "concept") and name and str(code).startswith("BK"):
                catalog[(kind, name)] = {"code": code, "name": name, "kind": kind,
                                          "mapping_asof": p.stem, "change_pct_indicative": None}
        for item in snap.get("hot_sectors", []):
            kind, code, name = item.get("board_type"), item.get("code"), item.get("name")
            if kind in ("industry", "concept") and name and str(code).startswith("BK"):
                catalog[(kind, name)] = {"code": code, "name": name, "kind": kind,
                                          "mapping_asof": p.stem, "change_pct_indicative": None}
    return catalog

def effective_close(root, day):
    """Render and score a dated revision if one exists; keep original close immutable."""
    version = data_path(root, "close_revisions", day)
    return load_json(version if version.exists() else data_path(root, "close", day))

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
    started = time.monotonic()
    def past_budget():
        return time.monotonic() - started >= MAX_COLLECTION_SECONDS
    print(f"GMR_CLOSE stage=benchmark day={day}", flush=True)
    benchmark = safe_bar("1.000300", day, warnings, "沪深300")
    if benchmark["status"] != "ok":
        benchmark = yahoo_benchmark_fallback(day, warnings)
    forecast_path = data_path(root, "forecasts", day)
    frozen = load_json(forecast_path) if forecast_path.exists() else None
    plan, forecast_status, morning_analysis_sha256 = observation_plan(day, root, frozen)
    print(f"GMR_CLOSE stage=boards elapsed={time.monotonic()-started:.1f}s benchmark={benchmark['status']}", flush=True)
    live_boards = list_sectors("industry", warnings) + list_sectors("concept", warnings)
    known = historical_board_catalog(root, day)
    board_index = {(b["kind"], b["name"]): b for b in live_boards}
    for identity, board in known.items():
        board_index.setdefault(identity, board)
    boards = list(board_index.values())
    if not live_boards and known:
        warnings.append("board listing unavailable; only previous verified board identities reused, same-day K-lines independently fetched")
    print(f"GMR_CLOSE stage=groups elapsed={time.monotonic()-started:.1f}s board_count={len(boards)}", flush=True)
    board_by_kind_name = {(b["kind"], b["name"]): b for b in boards}
    selected = find_tracks(plan)
    observed_board_cache, stock_cache = {}, {}
    def board_price(board):
        key = board["code"]
        if key not in observed_board_cache:
            if past_budget():
                warnings.append("time budget exhausted before board: " + board["name"])
                return {"status": "unavailable", "change_pct": None, "market_date": None}
            observed_board_cache[key] = safe_bar("90." + key, day, warnings, board["name"])
            time.sleep(0.2)
        return observed_board_cache[key]
    def stock_price(item):
        code, market, name = item
        key = market + "." + code
        if key not in stock_cache:
            if past_budget():
                warnings.append("time budget exhausted before stock: " + name)
                return {"code": code, "name": name, "market": market,
                        "status": "unavailable", "change_pct": None, "market_date": None}
            stock_cache[key] = {"code": code, "name": name, "market": market,
                                **safe_bar(key, day, warnings, name)}
            time.sleep(0.2)
        return stock_cache[key]
    groups = []
    observed_keys = set()
    for entry in selected:
        components = []
        tracks = entry["tracks"]
        if not tracks:
            # An unconfigured new topic may use an exact-name board; this is deterministic,
            # never a post-close search for the best-performing "similar" board.
            label = entry["sector"].strip()
            kind = next((k for k in ("industry", "concept") if (k, label) in board_by_kind_name), None)
            if kind:
                tracks = [{"key": "exact:" + label, "name": label,
                           "board_names": [label], "board_type": kind, "stocks": []}]
                warnings.append("new morning sector exact-name matched without preselected stocks: " + label)
            else:
                warnings.append("unmapped morning sector; cannot score: " + label)
        for track in tracks:
            matches = [board_by_kind_name[(track["board_type"], alias)]
                       for alias in track["board_names"]
                       if (track["board_type"], alias) in board_by_kind_name]
            matched = matches[0] if matches else None
            # User-approved and frozen vendor ID can bypass broken board-list API.
            if (track.get("user_approved") and str(track.get("board_code", "")).startswith("BK")
                    and str(track["board_code"])[2:].isdigit()):
                matched = {"code": track["board_code"],
                           "name": track.get("board_name") or track["board_names"][0],
                           "kind": track["board_type"]}
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
        hit = ((move > 0 if bias == "positive" else move < 0)
               if frozen and eligible and move != 0 and bias in ("positive", "negative") else None)
        groups.append({"sector": entry["sector"], "bias": bias, "reason": entry["reason"],
                       "components": components, "aggregated_change_pct": move,
                       "excess_vs_csi300_pct": round(move - benchmark["change_pct"], 4)
                       if move is not None and benchmark.get("status") == "ok" else None,
                       "direction_hit": hit,
                       "evaluation": "directional" if hit is not None
                       else "unfrozen_observation" if not frozen else "not_scorable"})
    print(f"GMR_CLOSE stage=hot elapsed={time.monotonic()-started:.1f}s groups={len(groups)}", flush=True)
    hot = []
    for board in sorted(live_boards, key=lambda b: b["change_pct_indicative"] if isinstance(b["change_pct_indicative"], (int, float)) else -999, reverse=True):
        if past_budget():
            warnings.append("time budget exhausted; remaining hot sector scan skipped")
            break
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
    observed_count = sum(
        quote.get("status") == "ok" and quote.get("market_date") == day
        for quote in [benchmark]
        + [c["quote"] for group in groups for c in group["components"]]
        + [s for group in groups for comp in group["components"] for s in comp["stocks"]]
        + [b["quote"] for b in hot]
    )
    if not observed_count:
        return "no_same_day_close_data: " + "; ".join(warnings)
    print(f"GMR_CLOSE stage=saving elapsed={time.monotonic()-started:.1f}s confirmed_quotes={observed_count}", flush=True)
    result = {"schema_version": "1.1", "report_date": day, "market_date": day,
              "captured_at_utc": now.isoformat(), "source": SOURCE,
              "benchmark": {"name": "沪深300", "quote": benchmark},
              "forecast_sha256": hashlib.sha256(forecast_path.read_bytes()).hexdigest() if frozen else None,
              "forecast_frozen_at_utc": frozen.get("frozen_at_utc") if frozen else None,
              "forecast_generated_at_utc": frozen.get("forecast_generated_at_utc") if frozen else None,
              "forecast_status": forecast_status,
              "morning_analysis_sha256": morning_analysis_sha256,
              "observed_close_instruments": observed_count,
              "predicted_groups": groups, "hot_sectors": hot,
              "news_clues": collect_news_clues(day, warnings), "warnings": warnings,
              "methodology": "没有冻结也应生成盘后收盘观察报告；只对已冻结的方向性组合研判计分，未冻结晨报只能定性对照。子板块需同日原名指数；代理、watch/mixed/neutral 不计分。"
             }
    dump_json(out, result)
    return "collected"

def enrich_close(day, root=ROOT):
    """Append one source-attributed corrected view if a sealed raw day lacks board quotes."""
    base_path = data_path(root, "close", day)
    revision_path = data_path(root, "close_revisions", day)
    if not base_path.exists():
        return "base_close_missing"
    if revision_path.exists():
        return "revision_already_exists"
    import copy
    raw = load_json(base_path)
    candidate = copy.deepcopy(raw)
    catalog = historical_board_catalog(root, day)
    forecast = data_path(root, "forecasts", day)
    if not catalog or not forecast.exists():
        return "historical_board_identity_or_forecast_missing"
    frozen = load_json(forecast)
    by_track = {x["key"]: x for x in frozen.get("watchlist", {}).get("tracks", [])}
    recovered = []
    attempted = set()
    for group in candidate.get("predicted_groups", []):
        for component in group.get("components", []):
            if component.get("quote", {}).get("status") == "ok":
                continue
            track = by_track.get(component.get("key"))
            if not track:
                # Unknown morning topics are not assigned after-the-fact substitutes.
                continue
            match = next((catalog[(track["board_type"], alias)] for alias in track.get("board_names", [])
                          if (track["board_type"], alias) in catalog), None)
            if not match:
                continue
            key = match["code"]
            if key not in attempted:
                attempted.add(key)
                print(f"GMR_CLOSE_ENRICH board={match['name']} code={key}", flush=True)
            quote = safe_bar("90." + key, day, candidate.setdefault("warnings", []), match["name"])
            if quote.get("status") != "ok" or quote.get("market_date") != day:
                why = candidate["warnings"][-1] if candidate.get("warnings") else "unknown"
                print(f"GMR_CLOSE_ENRICH_MISSING board={match['name']} code={key} reason={why}", flush=True)
                continue
            quote["recovered_at_utc"] = utc_now().isoformat()
            quote["identity_mapping_asof"] = match["mapping_asof"]
            component.update({"board_name": match["name"], "board_code": key,
                              "is_proxy": match["name"] != component.get("name"), "quote": quote})
            recovered.append(match["name"])
        components = group.get("components", [])
        eligible = bool(components) and all(
            c.get("quote", {}).get("status") == "ok" and not c.get("is_proxy")
            and c["quote"].get("market_date") == day for c in components)
        move = round(sum(c["quote"]["change_pct"] for c in components) / len(components), 4) if eligible else None
        benchmark = candidate.get("benchmark", {}).get("quote", {})
        bias = group.get("bias")
        group["aggregated_change_pct"] = move
        group["excess_vs_csi300_pct"] = (round(move - benchmark["change_pct"], 4)
            if move is not None and benchmark.get("status") == "ok" and benchmark.get("market_date") == day else None)
        group["direction_hit"] = ((move > 0 if bias == "positive" else move < 0)
            if candidate.get("forecast_sha256") and move is not None and move != 0
            and bias in ("positive", "negative") else None)
        group["evaluation"] = ("directional" if group["direction_hit"] is not None else
                               "unfrozen_observation" if not candidate.get("forecast_sha256") else "not_scorable")
    if not recovered:
        return "no_verified_same_day_board_quotes"
    candidate["revision_kind"] = "historically_confirmed_board_identity_with_same_day_kline"
    candidate["original_close_sha256"] = hashlib.sha256(base_path.read_bytes()).hexdigest()
    candidate["enriched_at_utc"] = utc_now().isoformat()
    candidate["recovered_board_names"] = sorted(set(recovered))
    candidate["warnings"].append("board index recovered via historical vendor identity and same-day Kline; original snapshot preserved")
    dump_json(revision_path, candidate)
    return "enriched: " + ", ".join(sorted(set(recovered)))

def usable_close_research(root, day):
    """A malformed or mislabeled research JSON must not block a valid facts-only page."""
    from .close_render import validate_close_analysis
    path = data_path(root, "close_analysis", day)
    if not path.exists():
        return False
    try:
        data = load_json(path)
        if data.get("report_date") != day or data.get("analysis_status") == "facts_only_pending_independent_research":
            return False
        return bool(validate_close_analysis(data))
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return False

def close_analysis_path(root, day):
    """Prefer valid authored research; otherwise use an explicit facts-only fallback."""
    researched = data_path(root, "close_analysis", day)
    fallback = data_path(root, "close_fact_analysis", day)
    return researched if usable_close_research(root, day) else fallback if fallback.exists() else researched

def render_close(root=ROOT):
    from .close_render import render_close_report, render_close_archive, render_close_home, validate_close_analysis
    snapshots = sorted((root / "data/close").glob("*/*/*.json"))
    ready = []
    for path in snapshots:
        day = path.stem
        analysis_path = close_analysis_path(root, day)
        if not analysis_path.exists():
            continue
        raw, analysis = effective_close(root, day), load_json(analysis_path)
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
    latest_raw = effective_close(root, max(ready)) if ready else None
    latest_analysis = load_json(close_analysis_path(root, max(ready))) if ready else None
    (folder / "index.html").write_text(render_close_home(latest_raw, latest_analysis), encoding="utf-8")
    return ready

def check_release(day, root=ROOT):
    from .close_render import validate_close_analysis
    raw_path = data_path(root, "close", day)
    analysis_path = close_analysis_path(root, day)
    html = root / "reports/close" / day[:4] / day[5:7] / (day + ".html")
    index = root / "reports/close/index.html"
    errors, warnings = [], []
    if not raw_path.exists(): errors.append("close snapshot missing")
    if not analysis_path.exists(): errors.append("verified close analysis missing")
    if not html.exists() or not index.exists(): errors.append("close HTML missing")
    if errors: return {"complete": False, "errors": errors, "warnings": warnings, "date": day}
    data, analysis = effective_close(root, day), load_json(analysis_path)
    if data_path(root, "close_analysis", day).exists() and not usable_close_research(root, day):
        warnings.append("authored research file failed validation; published facts-only fallback instead")
    facts_only = analysis.get("analysis_status") == "facts_only_pending_independent_research"
    if facts_only:
        warnings.append("facts-only automatic close published; independent GMR news research still pending")
        if analysis_path != data_path(root, "close_fact_analysis", day):
            errors.append("facts-only status used as independent research without verification")
        if analysis.get("news_sources") or analysis.get("new_events"):
            errors.append("facts-only report must not cite unverified news")
    try: validate_close_analysis(analysis)
    except ValueError as exc: errors.append(str(exc))
    if data.get("benchmark", {}).get("quote", {}).get("market_date") != day:
        warnings.append("benchmark unavailable for excess-return calculation")
    if not data.get("forecast_sha256") and any(x.get("direction_hit") is not None for x in data.get("predicted_groups", [])):
        errors.append("unfrozen observations must never be scored")
    if not any(
        q.get("status") == "ok" and q.get("market_date") == day
        for q in ([data.get("benchmark", {}).get("quote", {})]
                  + [s.get("quote", {}) for g in data.get("predicted_groups", [])
                     for s in g.get("components", [])]
                  + [stock for g in data.get("predicted_groups", []) for s in g.get("components", [])
                     for stock in s.get("stocks", [])]
                  + [h.get("quote", {}) for h in data.get("hot_sectors", [])])):
        errors.append("no verified same-day market observations")
    if not any(s.get("quote", {}).get("status") == "ok" for g in data.get("predicted_groups", []) for s in g.get("components", [])):
        warnings.append("no confirmed close quote for morning-observed sector indices")
    if day not in html.read_text(encoding="utf-8") or day not in index.read_text(encoding="utf-8"):
        errors.append("HTML missing expected date")
    from html import escape
    if escape(analysis.get("summary", "")) not in html.read_text(encoding="utf-8"):
        errors.append("analysis summary not found in HTML")
    warnings.extend(data.get("warnings", []))
    return {"complete": not errors and len(warnings) == 0, "published": not errors,
            "has_independent_research": not facts_only,
            "analysis_mode": "facts_only_fallback" if facts_only else "independent_research",
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
    mode.add_argument("--enrich-only", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = p.parse_args()
    day = args.date or utc_now().astimezone(BJ).date().isoformat()
    datetime.strptime(day, "%Y-%m-%d")
    if args.freeze_only: print(freeze_forecast(day))
    elif args.collect_only:
        result = collect_close(day)
        print(result)
        if result not in ("collected", "already_collected", "weekend", "not_collection_window"):
            raise SystemExit(1)
    elif args.render_only: print("rendered: " + str(render_close()))
    elif args.enrich_only: print(enrich_close(day))
    else:
        result = check_release(day)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("published", False): raise SystemExit(1)

if __name__ == "__main__":
    main()
