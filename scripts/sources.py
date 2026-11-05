"""Best-effort public data adapters. Never fill failed quotes with guessed numbers."""
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GlobalMarketRadar/1.0; research)"}
TOPICS = {
    "macro": "Federal Reserve OR US inflation OR US employment when:1d",
    "geopolitics": "geopolitics oil global markets when:1d",
    "china": "China stocks economy policy trade when:1d",
    "australia": "Reserve Bank Australia Australian dollar when:1d",
}

def read_url(url, timeout=18):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()

def yahoo_chart(symbol, interval="1d", period="14d"):
    params = urllib.parse.urlencode({"interval": interval, "range": period})
    escaped = urllib.parse.quote(symbol, safe="")
    last_error = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            data = json.loads(read_url(f"https://{host}/v8/finance/chart/{escaped}?{params}"))
            result = data.get("chart", {}).get("result")
            if not result:
                raise ValueError(str(data.get("chart", {}).get("error")))
            return result[0]
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Yahoo unavailable for {symbol}: {last_error}")

def parse_bars(chart):
    tz_name = chart.get("meta", {}).get("exchangeTimezoneName") or "UTC"
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc
    ts = chart.get("timestamp") or []
    quotes = (chart.get("indicators", {}).get("quote") or [{}])[0]
    close = quotes.get("close") or []
    bars = []
    for epoch, value in zip(ts, close):
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            observed = datetime.fromtimestamp(epoch, timezone.utc)
            bars.append({"value": float(value), "observed_at_utc": observed.isoformat(),
                         "market_date": observed.astimezone(local_tz).date().isoformat()})
    return bars

def normalize_quote(asset, daily_bars, intraday_bars=None, now=None):
    """FX latest observed hourly value vs previous DAILY observation; indices close vs preceding close."""
    if not daily_bars:
        raise ValueError("No valid daily bars")
    latest = daily_bars[-1]
    current = latest
    previous = daily_bars[-2] if len(daily_bars) > 1 else None
    kind = "daily_bar"
    if asset["category"] in ("us_index", "cn_index"):
        target_tz = ZoneInfo("America/New_York" if asset["category"] == "us_index" else "Asia/Shanghai")
        local_now = (now or datetime.now(timezone.utc)).astimezone(target_tz)
        exchange_date = datetime.fromisoformat(latest["market_date"]).date()
        close_hour = 16 if asset["category"] == "us_index" else 15
        kind = "daily_close" if exchange_date < local_now.date() or (exchange_date == local_now.date() and local_now.hour >= close_hour) else "daily_bar_live"
    if asset["category"] == "fx" and intraday_bars:
        hourly = intraday_bars[-1]
        if hourly["observed_at_utc"] > latest["observed_at_utc"]:
            current = hourly
            kind = "intraday_observation"
            if hourly["market_date"] > latest["market_date"]:
                previous = latest
    base = previous["value"] if previous else None
    value = current["value"]
    return {
        "key": asset["key"], "symbol": asset["symbol"], "label": asset["label"],
        "category": asset["category"], "unit": asset["unit"], "status": "ok",
        "value_kind": kind, "market_date": current["market_date"],
        "observed_at_utc": current["observed_at_utc"], "value": round(value, 8),
        "reference_close": round(base, 8) if base is not None else None,
        "reference_date": previous["market_date"] if previous else None,
        "change_pct": round((value / base - 1) * 100, 4) if base else None,
        "source": "Yahoo Finance chart API (unofficial)", "error": None
    }

# Prefer a second, exchange-specific source for Shanghai indices.
# This endpoint is unofficial and can fail; never create data if the response is invalid.
EASTMONEY_CN_INDEX = {"SSE": "1.000001", "CSI300": "1.000300"}

def eastmoney_index_quote(asset, now=None):
    """Use completed China-market daily bars, never the unclosed current session."""
    secid = EASTMONEY_CN_INDEX[asset["key"]]
    local_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Shanghai"))
    last_closed = local_now.date() if local_now.hour >= 16 else local_now.date() - timedelta(days=1)
    params = urllib.parse.urlencode({
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "0", "beg": (last_closed - timedelta(days=30)).strftime("%Y%m%d"),
        "end": last_closed.strftime("%Y%m%d"), "lmt": "25"
    })
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + params
    response = json.loads(read_url(url, timeout=10))
    payload = response.get("data") or {}
    if str(payload.get("code")) != secid.split(".")[1]:
        raise ValueError(f"Unexpected Eastmoney index identifier for {secid}")
    bars = []
    for item in payload.get("klines") or []:
        values = item.split(",") if isinstance(item, str) else []
        if len(values) < 3:
            continue
        try:
            day = datetime.strptime(values[0], "%Y-%m-%d").date()
            close = float(values[2])
        except (ValueError, TypeError):
            continue
        if day <= last_closed and math.isfinite(close) and close > 0:
            bars.append((day, close))
    bars = sorted(set(bars))
    if len(bars) < 2:
        raise ValueError(f"Insufficient completed Eastmoney index bars for {secid}")
    (prev_day, previous), (day, current) = bars[-2:]
    if abs(current / previous - 1) > 0.25:
        raise ValueError("Implausible daily broad-index change, rejecting source")
    return {
        "key": asset["key"], "symbol": asset["symbol"], "label": asset["label"],
        "category": asset["category"], "unit": asset["unit"], "status": "ok",
        "value_kind": "daily_close", "market_date": day.isoformat(),
        "observed_at_utc": None, "value": round(current, 8),
        "reference_close": round(previous, 8), "reference_date": prev_day.isoformat(),
        "change_pct": round((current / previous - 1) * 100, 4),
        "source": "Eastmoney public daily K-line API (unofficial)",
        "source_url": "https://quote.eastmoney.com/zs" + secid.split(".")[1] + ".html",
        "error": None
    }

def collect_quotes(assets):
    results = []
    for asset in assets:
        eastmoney_error = None
        if asset["key"] in EASTMONEY_CN_INDEX:
            try:
                results.append(eastmoney_index_quote(asset))
                time.sleep(0.2)
                continue
            except Exception as exc:
                eastmoney_error = str(exc)[:180]
        try:
            bars = parse_bars(yahoo_chart(asset["symbol"], "1d", "14d"))
            hourly = None
            if asset["category"] == "fx":
                try:
                    hourly = parse_bars(yahoo_chart(asset["symbol"], "60m", "5d"))
                except Exception:
                    pass
            result = normalize_quote(asset, bars, hourly)
            if eastmoney_error:
                result["fallback_note"] = f"Eastmoney not available: {eastmoney_error}"
            results.append(result)
        except Exception as exc:
            results.append({
                "key": asset["key"], "symbol": asset["symbol"], "label": asset["label"],
                "category": asset["category"], "unit": asset["unit"], "status": "unavailable",
                "value_kind": None, "market_date": None, "observed_at_utc": None,
                "value": None, "reference_close": None, "reference_date": None,
                "change_pct": None, "source": "Yahoo Finance chart API (unofficial)",
                "error": str(exc)[:300], "fallback_note": eastmoney_error
            })
        time.sleep(0.2)
    # Two indices on the same exchange session should not silently disagree
    # on their last available market date.
    latest_cn = max((q["market_date"] for q in results
                     if q.get("category") == "cn_index" and q.get("status") == "ok"
                     and q.get("market_date")), default=None)
    for q in results:
        if (q.get("category") == "cn_index" and q.get("status") == "ok"
                and latest_cn and q.get("market_date") < latest_cn):
            q["status"] = "stale"
            q["error"] = f"Quote dated {q['market_date']} is older than peer CN index {latest_cn}"
    return results

def parse_rss(data, topic, now=None):
    root = ET.fromstring(data)
    now = now or datetime.now(timezone.utc)
    out = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        published = (node.findtext("pubDate") or "").strip()
        source = (node.findtext("source") or "Google News RSS").strip()
        if not title or not url:
            continue
        try:
            published_dt = parsedate_to_datetime(published).astimezone(timezone.utc)
        except Exception:
            continue
        if not (now - timedelta(hours=40) <= published_dt <= now + timedelta(minutes=5)):
            continue
        event_id = hashlib.sha256((url + "|" + title).encode()).hexdigest()[:16]
        out.append({"event_id": event_id, "topic": topic, "headline": title,
                    "published_at_utc": published_dt.isoformat(), "source": source,
                    "url": url, "verification": "rss_headline_unverified"})
    return out

def collect_news(now=None):
    now = now or datetime.now(timezone.utc)
    events, errors, seen = [], [], set()
    for topic, query in TOPICS.items():
        params = urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        try:
            items = parse_rss(read_url("https://news.google.com/rss/search?" + params), topic, now)
            for item in items[:5]:
                if item["event_id"] not in seen:
                    events.append(item)
                    seen.add(item["event_id"])
        except Exception as exc:
            errors.append({"topic": topic, "error": str(exc)[:240]})
    events.sort(key=lambda r: r["published_at_utc"], reverse=True)
    return events[:16], errors
