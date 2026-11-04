"""HTML renderer: escapes every externally supplied field and avoids fabricated analysis."""
from datetime import datetime
from html import escape
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from pathlib import Path
import json

STYLE = """
:root{color-scheme:light;--ink:#14213b;--muted:#607083;--line:#e1e7ed;--blue:#2846ac;--bg:#f6f8fc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:system-ui,-apple-system,"Segoe UI","PingFang SC",sans-serif;color:var(--ink);line-height:1.65}
main{max-width:1050px;margin:0 auto;padding:30px 20px 80px}header{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:22px 0}
.brand{font-size:12px;letter-spacing:.2em;font-weight:800;color:var(--blue)}h1{font-size:clamp(28px,4vw,43px);letter-spacing:-.03em;margin:4px 0}
h2{font-size:20px;margin:30px 0 12px}h3{font-size:16px;margin:10px 0}p{margin:8px 0;color:#39495d}
a{color:#2453b8;text-decoration:none}a:hover{text-decoration:underline}.sub{font-size:13px;color:var(--muted)}
.card,.metric{background:white;border:1px solid var(--line);border-radius:16px;padding:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:12px}
.metric .label{font-size:12px;color:var(--muted)}.metric .value{font-size:25px;font-weight:750;font-variant-numeric:tabular-nums}
.up{color:#c43d4e}.down{color:#148064}.muted{color:var(--muted)}.pill{background:#eef2ff;color:#3c4b88;border-radius:100px;padding:5px 11px;font-size:12px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:11px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}
.table-wrap{overflow-x:auto}.news{padding:13px 0;border-bottom:1px solid var(--line)}.news:last-child{border-bottom:0}
.news-card{margin:14px 0;padding:20px;border:1px solid var(--line);border-radius:14px;background:#fff}
.digest-overview{padding:18px 20px;border:1px solid #dce5fa;background:#eff4ff;border-radius:14px}
.digest-overview p{margin:5px 0}.news-card h3{margin:0 0 10px}.impact{background:#f6f8fc;padding:11px 14px;border-radius:9px;margin:10px 0}
.source-list{list-style:none;padding-left:0;margin:0}.source-list li{padding:11px 0;border-bottom:1px solid var(--line)}.source-list li:last-child{border:0}
.cite{font-size:12px;font-weight:700}.hint{color:var(--muted);font-size:12px}.quality{margin-top:24px;padding:10px 0;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
details{margin-top:14px}summary{cursor:pointer;font-weight:600;color:var(--blue)}.outdated{background:#fff9ed}.warn{color:#92651a;font-weight:650}.report-stage{margin-top:10px;padding:10px 12px;background:#eef3ff;border-radius:8px;font-size:13px}.small{font-size:12px;color:var(--muted)}.notice{border-left:3px solid #e9a23b;padding:10px 16px;background:#fff8e8;border-radius:4px}
.bias-tag{display:inline-flex;align-items:center;gap:6px;border-radius:7px;padding:3px 10px;font-size:12px;font-weight:750;line-height:1.5;white-space:nowrap;border:1px solid transparent;vertical-align:baseline}
.bias-tag small{font-size:11px;font-weight:600;opacity:.83}
.bias-positive{background:#dcfce7;color:#166534;border-color:#86efac}
.bias-negative{background:#fee2e2;color:#991b1b;border-color:#fca5a5}
.bias-mixed{background:#ede9fe;color:#5b21b6;border-color:#c4b5fd}
.bias-watch{background:#fef3c7;color:#92400e;border-color:#fcd34d}
.bias-neutral{background:#e2e8f0;color:#334155;border-color:#cbd5e1}
.bias-unknown{background:#f1f5f9;color:#64748b;border-color:#cbd5e1}
.bias-summary{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:2px 0 16px}
.sector-list{padding-left:21px}.sector-list li{margin:8px 0}.sector-list .bias-tag{margin:0 3px}
.site-nav{display:flex;flex-wrap:wrap;gap:10px 20px;padding:9px 0 19px;border-bottom:1px solid var(--line);font-weight:650;font-size:14px}
footer{margin-top:40px;color:var(--muted);font-size:12px}ul{padding-left:20px}
@media(max-width:600px){header{align-items:flex-start;flex-direction:column}main{padding:14px 14px 50px}th,td{padding:8px}}
"""

def safe(value):
    return escape(str(value)) if value is not None else "—"

def shell(title, content, home):
    prefix = "" if home == "reports/archive.html" else (home[:-len("index.html")] if home.endswith("index.html") else "")
    navigation = ('<nav class="site-nav"><a href="' + prefix + 'index.html">最新晨报</a>'
                  '<a href="' + prefix + 'reports/close/index.html">盘后复盘</a>'
                  '<a href="' + prefix + 'reports/archive.html">晨报历史</a>'
                  '<a href="' + prefix + 'reports/close/archive.html">盘后历史</a></nav>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="description" content="全球市场雷达：汇率、美股、国际事件与A股盘前研究">'
            f'<title>{safe(title)} · Global Market Radar</title><style>{STYLE}</style></head><body>'
            '<main><header><div><div class="brand">GLOBAL MARKET RADAR</div>'
            f'<h1>{safe(title)}</h1><div class="sub">全球市场数据 · 重要新闻 · A股盘前研究</div></div>'
            f'<a class="pill" href="{safe(home)}">{"查看历史晨报" if home.endswith("archive.html") else "返回最新晨报"}</a></header>{navigation}{content}'
            '<footer>仅供研究和信息整理，不构成投资建议。行情可能延迟；请核对来源与时间戳。</footer>'
            '</main></body></html>')

def metric(quote):
    if quote["status"] != "ok":
        return f'<article class="metric"><div class="label">{safe(quote["label"])}</div><div class="value muted">暂无数据</div><div class="small">{safe(quote.get("error"))}</div></article>'
    pct = quote.get("change_pct")
    cls = "up" if pct is not None and pct > 0 else "down" if pct is not None and pct < 0 else "muted"
    sign = "+" if pct is not None and pct > 0 else ""
    delta = f'{sign}{pct:.2f}%' if pct is not None else "无可比值"
    provenance = (" · 补采UTC: " + safe(quote["supplement_collected_at_utc"])) if quote.get("supplement_collected_at_utc") else ""
    return (f'<article class="metric"><div class="label">{safe(quote["label"])}</div>'
            f'<div class="value">{quote["value"]:,.4f}</div><div class="{cls}">{delta}</div>'
            f'<div class="small">{safe(quote["market_date"])} · {safe(quote["value_kind"])}{provenance}</div></article>')

BIAS_LABELS = {
    "positive": ("偏利好", "积极因素相对占优"),
    "negative": ("偏利空", "消极因素相对占优"),
    "mixed": ("多空交织", "积极与消极因素并存"),
    "watch": ("重点观察", "证据不足或关键条件尚未触发"),
    "neutral": ("中性", "现有证据显示影响相对有限"),
}

def bias_tag(value):
    """Compact, accessible colored bias badge; unknown values are not silently neutral."""
    key = value.strip().lower() if isinstance(value, str) else ""
    if key not in BIAS_LABELS:
        return '<span class="bias-tag bias-unknown" title="未识别的倾向标签">未分类</span>'
    label, meaning = BIAS_LABELS[key]
    return (f'<span class="bias-tag bias-{key}" title="{safe(meaning)}">'
            f'{safe(label)} <small>({key})</small></span>')

def valid_url(value):
    """Only explicit HTTPS URLs can become clickable links."""
    if not isinstance(value, str) or not value.startswith("https://"):
        return None
    parsed = urlsplit(value)
    return value if parsed.hostname and not parsed.username and not parsed.password else None

def source_catalog(analysis):
    """Structured citations take priority; legacy evidence_urls remain readable."""
    sources, seen_urls, seen_ids = [], set(), set()
    if not isinstance(analysis, dict):
        return sources
    for item in analysis.get("news_sources", []):
        if not isinstance(item, dict):
            continue
        sid, url = item.get("id"), valid_url(item.get("url"))
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", sid):
            continue
        if not url or sid in seen_ids or url in seen_urls:
            continue
        sources.append({"id": sid, "url": url, "title": item.get("title") or item.get("publisher") or url,
                        "publisher": item.get("publisher") or "未注明媒体",
                        "published_at_utc": item.get("published_at_utc"),
                        "verification": item.get("verification") or "reported"})
        seen_urls.add(url)
        seen_ids.add(sid)
    for url in analysis.get("evidence_urls", []):
        url = valid_url(url)
        if not url or url in seen_urls:
            continue
        i = 1
        while f"L{i}" in seen_ids:
            i += 1
        sid = f"L{i}"
        sources.append({"id": sid, "url": url, "title": "历史分析参考资料",
                        "publisher": "原有分析引用", "published_at_utc": None,
                        "verification": "legacy_reference"})
        seen_urls.add(url)
        seen_ids.add(sid)
    return sources

def validate_analysis(analysis):
    """Avoid publishing new story claims without resolvable citations."""
    digest = analysis.get("news_digest") if isinstance(analysis, dict) else None
    if digest is None:
        return
    if not isinstance(digest, dict):
        raise ValueError("news_digest must be an object")
    items = digest.get("items", [])
    if not isinstance(items, list) or len(items) > 6:
        raise ValueError("news_digest.items must be a list with at most six stories")
    known = {x["id"] for x in source_catalog(analysis) if x["verification"] != "legacy_reference"}
    if items and not digest.get("overview"):
        raise ValueError("news_digest.overview required when stories exist")
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip()
                                                for k in ("title", "summary", "market_impact")):
            raise ValueError(f"news_digest.items[{i}] requires title, summary, market_impact")
        refs = item.get("source_ids", [])
        if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x in known for x in refs):
            raise ValueError(f"news_digest.items[{i}] must reference existing news_sources ids")

def render_news_digest(analysis, sources):
    digest = analysis.get("news_digest") if isinstance(analysis, dict) else None
    items = digest.get("items", []) if isinstance(digest, dict) else []
    if not items:
        return ('<div class="notice">本期尚无经过核验和筛选的新闻综述。原始新闻线索仍保存在第 06 节，'
                '未核实的 RSS 标题不会自动转换成市场结论。</div>')
    known = {s["id"] for s in sources}
    overview = '<div class="digest-overview"><strong>今日核心脉络</strong><p>' + safe(digest.get("overview")) + '</p></div>'
    stories = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        citations = " ".join(f'<a class="cite" href="#ref-{safe(sid)}">[{safe(sid)}]</a>'
                             for sid in item.get("source_ids", []) if sid in known)
        importance = safe(item.get("importance", "关注"))
        stories.append('<article class="news-card"><div class="hint">重要性：' + importance +
                       '</div><h3>' + safe(item.get("title")) + '</h3><p><strong>事件：</strong>' +
                       safe(item.get("summary")) + '</p><div class="impact"><strong>市场影响：</strong>' +
                       safe(item.get("market_impact")) + '</div><div class="hint">参考来源：' +
                       citations + '</div></article>')
    return overview + "".join(stories)

def render_sources(analysis, data, sources):
    if sources:
        entries = []
        for src in sources:
            entries.append('<li id="ref-' + safe(src["id"]) + '"><span class="cite">[' +
                           safe(src["id"]) + ']</span> <a target="_blank" rel="noopener noreferrer" href="' +
                           safe(src["url"]) + '">' + safe(src["title"]) + '</a><div class="small">' +
                           safe(src["publisher"]) + ' · ' + safe(src.get("published_at_utc")) +
                           ' · 核验状态：' + safe(src.get("verification")) + '</div></li>')
        citations = '<ul class="source-list">' + "".join(entries) + '</ul>'
    else:
        citations = '<p>暂无分析引用。新闻线索不能直接充当已核实的来源。</p>'
    raw = []
    for entry in data.get("news", []):
        url = valid_url(entry.get("url"))
        if not url:
            continue
        raw.append('<li><a target="_blank" rel="noopener noreferrer" href="' +
                   safe(url) + '">' + safe(entry.get("headline")) + '</a><div class="small">' +
                   safe(entry.get("source")) + ' · ' + safe(entry.get("published_at_utc")) +
                   ' · RSS 标题（未经独立核验）</div></li>')
    details = ('<details><summary>展开全部原始 RSS 新闻线索（' + str(len(raw)) +
               ' 条）</summary><ul class="source-list">' + "".join(raw) +
               '</ul></details>') if raw else '<p class="small">本期无原始 RSS 新闻线索。</p>'
    return ('<div class="card"><p>本次分析引用的报道优先展示；全部原始新闻线索折叠保存。'
            '引用报道与市场影响分析不等于已确认因果关系。</p>' +
            citations + details + '</div>')

def beijing_time(value):
    if not value:
        return "未提供"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return safe(value)
        return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return safe(value)

def quote_quality_flags(data):
    """Compare dates within the same exchange, not to the report date."""
    cn_dates = [q.get("market_date") for q in data.get("quotes", [])
                if q.get("category") == "cn_index" and q.get("status") == "ok"
                and q.get("market_date")]
    latest_cn = max(cn_dates) if cn_dates else None
    flags = {}
    for q in data.get("quotes", []):
        if q.get("status") != "ok":
            continue
        messages = []
        if q.get("category") == "cn_index" and latest_cn and q.get("market_date") and q["market_date"] < latest_cn:
            messages.append("同市场指数已更新至 " + latest_cn + "，此报价疑似滞后")
        if q.get("change_pct") is None:
            messages.append("缺少可比较涨跌幅的参考日线")
        if messages:
            flags[q.get("key")] = "；".join(messages)
    return flags

def market_date_context(data):
    quotes = {q.get("key"): q for q in data.get("quotes", [])}
    fx = quotes.get("USD_CNY", {}).get("market_date")
    us = quotes.get("NASDAQ", {}).get("market_date")
    cn = max((q.get("market_date") for q in data.get("quotes", [])
              if q.get("category") == "cn_index" and q.get("status") == "ok"
              and q.get("market_date")), default=None)
    return ("行情所属日期：汇率 " + safe(fx) + "（盘中/最新可得） · 美股 " +
            safe(us) + "（上一交易日收盘） · A股 " + safe(cn) +
            "（最近可得收盘）。报告日期不等于每项资产的交易日期。")

def render_report(data, analysis=None, home="index.html"):
    date = data["report_date"]
    by_key = {x["key"]: x for x in data.get("quotes", [])}
    core = (("USD_CNY", "美元/人民币"), ("AUD_CNY", "澳元/人民币"),
            ("NASDAQ", "纳斯达克综合指数"), ("SP500", "标普500"),
            ("DOW", "道琼斯工业平均指数"), ("AUD_USD", "澳元/美元"))
    important = [by_key.get(k, {"label": label, "status": "unavailable",
                               "error": "历史快照尚未采集该指标"}) for k, label in core]
    cards = '<div class="grid">' + "".join(metric(x) for x in important) + "</div>"
    quality_flags = quote_quality_flags(data)
    rows = []
    kind_labels = {"daily_close": "最近交易日收盘", "daily_bar": "日线",
                   "daily_bar_live": "尚未确认收盘",
                   "intraday_observation": "盘中观测",
                   "official_daily_close": "交易所官方收盘"}
    for q in data.get("quotes", []):
        val = f'{q["value"]:,.4f}' if q["value"] is not None else "—"
        change = f'{q["change_pct"]:+.2f}%' if q.get("change_pct") is not None else "—"
        revised = bool(q.get("correction_note"))
        label = safe(q["label"]) + ("（来源修正）" if revised else "（补采）" if q.get("supplement_collected_at_utc") else "")
        issue = quality_flags.get(q.get("key"))
        status = ('<span class="warn">' + safe(issue) + '</span>') if issue else ('已核实修正' if revised else safe(q["status"]))
        source_note = (' <a target="_blank" rel="noopener noreferrer" href="' +
                       safe(q["source_url"]) + '">官方来源</a>') if revised and valid_url(q.get("source_url")) else ""
        row_class = ' class="outdated"' if issue else ""
        rows.append(f'<tr{row_class}><td>{label}{source_note}</td><td>{val}</td><td>{change}</td>'
                    f'<td>{safe(q["market_date"])}</td><td>{safe(kind_labels.get(q.get("value_kind"), q.get("value_kind")))}</td>'
                    f'<td>{safe(q["observed_at_utc"])}</td><td>{status}</td></tr>')
    table = ('<div class="card table-wrap"><table><thead><tr><th>资产</th><th>最新值</th><th>相对前日</th>'
             '<th>行情日期</th><th>类型</th><th>UTC K线时间</th><th>状态</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
             '<p class="small">汇率日内观测值与前一交易日参考价比较；美股指数使用最近一个已结束交易日收盘价。'
             '日线 UTC 时间可能是 K 线开盘时间，而非收盘时间；daily_bar_live 表示未确认收盘。'
             '不同市场采用自己的交易日期，不能统一改成报告日期；若同一市场出现日期不一致，页面会警示。'
             '价格主要来自 Yahoo Finance 非官方行情接口，带来源修正的记录标有官方链接。</p></div>')
    sources = source_catalog(analysis)
    digest_html = render_news_digest(analysis, sources)
    references_html = render_sources(analysis, data, sources)
    if analysis:
        summary = '<div class="card"><p>' + safe(analysis.get("market_summary", "暂无综述")) + '</p></div>'
        sectors = "".join('<li><strong>' + safe(s.get("sector")) + '</strong> ' +
                          bias_tag(s.get("bias")) + '：' + safe(s.get("reason")) + '</li>'
                          for s in analysis.get("a_share_sectors", []) if isinstance(s, dict))
        outlook = ('<div class="card"><div class="bias-summary"><strong>总体倾向：</strong>' +
                   bias_tag(analysis.get("a_share_bias")) + '</div><p>' +
                   safe(analysis.get("a_share_outlook")) + '</p><ul class="sector-list">' + sectors +
                   '</ul><p><strong>风险：</strong>' + safe("；".join(analysis.get("risks", []))) +
                   '</p><div class="small">分析时间：' + safe(analysis.get("generated_at_utc")) +
                   ' · 不确定性：' + safe(analysis.get("uncertainty")) + '</div></div>')
    else:
        summary = '<div class="notice">市场解读尚未更新。行情事实不能自动推导出涨跌原因。</div>'
        outlook = '<div class="card"><p>等待核实后的盘前研判；无可靠证据时不作方向判断。</p></div>'
    supplement_note = (" · 补采： " + ", ".join(safe(x["key"]) + "@" + safe(x["collected_at_utc"])
                                          for x in data.get("supplements", []))) if data.get("supplements") else ""
    issues = quality_flags
    quality = ('<div class="quality">数据状态：' +
               str(sum(q["status"] == "ok" for q in data.get("quotes", []))) + '/' +
               str(len(data.get("quotes", []))) + ' 项行情可用 · ' +
               str(len(data.get("news", []))) + ' 条原始 RSS 线索 · 采集时刻（UTC）：' +
               safe(data.get("collected_at_utc")) + supplement_note +
               (' · ' + str(len(issues)) + ' 项指标需注意' if issues else '') +
               (' · ' + str(len(data.get("quote_revisions", []))) + ' 项来源修正' if data.get("quote_revisions") else '') +
               ' · 原始快照与修正来源均可在仓库查阅。</div>')
    stage = ('完整分析版 · 分析生成（北京时间）：' + beijing_time(analysis.get("generated_at_utc"))
             if analysis and analysis.get("news_digest", {}).get("items")
             else '基础行情版 · 深度新闻与A股研判尚待分析更新')
    heading = ('<div class="report-stage"><strong>' + safe(stage) + '</strong></div>'
               '<p class="small">' + market_date_context(data) + '</p>')
    body = ('<p class="sub">报告日期（北京时间）：' + safe(date) + ' · 数据采集时间（UTC）：' +
            safe(data.get("collected_at_utc")) + '</p>' + heading +
            '<h2>01 / 关键市场数据</h2>' + cards +
            '<h2>02 / 全量监测指标</h2>' + table + '<h2>03 / 昨夜市场走势与原因</h2>' + summary +
            '<h2>04 / 国际重要新闻综述</h2>' + digest_html +
            '<h2>05 / A股开盘前研判</h2>' + outlook +
            '<h2>06 / 新闻来源与参考资料</h2>' + references_html + quality)
    return shell("全球市场晨报 · " + date, body, home)

def render_archive(dates):
    lines = ''.join(f'<li><a href="{safe(d[:4])}/{safe(d[5:7])}/{safe(d)}.html">{safe(d)}</a></li>'
                    for d in sorted(dates, reverse=True))
    return shell("历史晨报", '<div class="card"><p>按北京时间报告日期归档。</p><ul>' +
                 (lines or "<li>暂无已生成的报告</li>") + '</ul></div>', "../index.html")

def pending_home():
    return shell("全球市场雷达", '<div class="card"><h2>自动化已部署，等待首次采集</h2>'
                 '<p>每日北京时间 08:15 计划启动 GitHub Actions。市场数据不可用时不会使用虚构数值。</p>'
                 '<p><a href="reports/archive.html">查看历史报告</a></p></div>', "index.html")
