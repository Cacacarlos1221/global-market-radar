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

def normalize_quote(asset, daily_bars, intraday_bars=None):
    """FX latest observed hourly value vs previous DAILY observation; indices close vs preceding close."""
    if not daily_bars:
        raise ValueError("No valid daily bars")
    latest = daily_bars[-1]
    current = latest
    previous = daily_bars[-2] if len(daily_bars) > 1 else None
    kind = "daily_close"
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

def collect_quotes(assets):
    results = []
    for asset in assets:
        try:
            bars = parse_bars(yahoo_chart(asset["symbol"], "1d", "14d"))
            hourly = None
            if asset["category"] == "fx":
                try:
                    hourly = parse_bars(yahoo_chart(asset["symbol"], "60m", "5d"))
                except Exception:
                    pass
            results.append(normalize_quote(asset, bars, hourly))
        except Exception as exc:
            results.append({
                "key": asset["key"], "symbol": asset["symbol"], "label": asset["label"],
                "category": asset["category"], "unit": asset["unit"], "status": "unavailable",
                "value_kind": None, "market_date": None, "observed_at_utc": None,
                "value": None, "reference_close": None, "reference_date": None,
                "change_pct": None, "source": "Yahoo Finance chart API (unofficial)",
                "error": str(exc)[:300]
            })
        time.sleep(0.2)
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
