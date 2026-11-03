"""HTML renderer: escapes every externally supplied field and avoids fabricated analysis."""
from html import escape
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
.small{font-size:12px;color:var(--muted)}.notice{border-left:3px solid #e9a23b;padding:10px 16px;background:#fff8e8;border-radius:4px}
footer{margin-top:40px;color:var(--muted);font-size:12px}ul{padding-left:20px}
@media(max-width:600px){header{align-items:flex-start;flex-direction:column}main{padding:14px 14px 50px}th,td{padding:8px}}
"""

def safe(value):
    return escape(str(value)) if value is not None else "—"

def shell(title, content, home):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="description" content="全球市场雷达：汇率、美股、国际事件与A股盘前研究">'
            f'<title>{safe(title)} · Global Market Radar</title><style>{STYLE}</style></head><body>'
            '<main><header><div><div class="brand">GLOBAL MARKET RADAR</div>'
            f'<h1>{safe(title)}</h1><div class="sub">全球市场数据 · 重要新闻 · A股盘前研究</div></div>'
            f'<a class="pill" href="{safe(home)}">返回最新晨报</a></header>{content}'
            '<footer>仅供研究和信息整理，不构成投资建议。行情可能延迟；请核对来源与时间戳。</footer>'
            '</main></body></html>')

def metric(quote):
    if quote["status"] != "ok":
        return f'<article class="metric"><div class="label">{safe(quote["label"])}</div><div class="value muted">暂无数据</div><div class="small">{safe(quote.get("error"))}</div></article>'
    pct = quote.get("change_pct")
    cls = "up" if pct is not None and pct > 0 else "down" if pct is not None and pct < 0 else "muted"
    sign = "+" if pct is not None and pct > 0 else ""
    delta = f'{sign}{pct:.2f}%' if pct is not None else "无可比值"
    return (f'<article class="metric"><div class="label">{safe(quote["label"])}</div>'
            f'<div class="value">{quote["value"]:,.4f}</div><div class="{cls}">{delta}</div>'
            f'<div class="small">{safe(quote["market_date"])} · {safe(quote["value_kind"])}</div></article>')

def render_report(data, analysis=None, home="index.html"):
    date = data["report_date"]
    by_key = {x["key"]: x for x in data.get("quotes", [])}
    important = [by_key[k] for k in ("AUD_CNY", "AUD_USD", "NASDAQ", "SP500", "DOW") if k in by_key]
    cards = '<div class="grid">' + "".join(metric(x) for x in important) + "</div>"
    rows = []
    for q in data.get("quotes", []):
        val = f'{q["value"]:,.4f}' if q["value"] is not None else "—"
        change = f'{q["change_pct"]:+.2f}%' if q.get("change_pct") is not None else "—"
        rows.append(f'<tr><td>{safe(q["label"])}</td><td>{val}</td><td>{change}</td>'
                    f'<td>{safe(q["market_date"])}</td><td>{safe(q["observed_at_utc"])}</td>'
                    f'<td>{safe(q["status"])}</td></tr>')
    table = ('<div class="card table-wrap"><table><thead><tr><th>资产</th><th>最新值</th><th>相对前日</th>'
             '<th>行情日期</th><th>UTC数据时间</th><th>状态</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
             '<p class="small">汇率日内观测值与前一交易日参考价比较；美国指数使用最近一个已结束交易日收盘价。'
             '假期可能显示上一交易日行情，不代表当日开盘。价格源：Yahoo Finance 非官方行情接口。</p></div>')
    events = []
    for e in data.get("news", []):
        events.append('<article class="news"><a target="_blank" rel="noopener noreferrer" href="' +
                      safe(e["url"]) + '"><strong>' + safe(e["headline"]) + '</strong></a>'
                      '<div class="small">' + safe(e["source"]) + ' · ' + safe(e["published_at_utc"]) +
                      ' · ' + safe(e["topic"]) + '</div></article>')
    news_html = '<div class="card">' + ("".join(events) if events else "<p>暂无可用新闻源数据。</p>") + '</div>'
    if analysis:
        summary = '<div class="card"><p>' + safe(analysis.get("market_summary", "暂无综述")) + '</p></div>'
        sectors = "".join('<li><strong>' + safe(s.get("sector")) + '</strong> (' +
                          safe(s.get("bias")) + ')：' + safe(s.get("reason")) + '</li>'
                          for s in analysis.get("a_share_sectors", []) if isinstance(s, dict))
        outlook = ('<div class="card"><p><strong>总体倾向：</strong>' + safe(analysis.get("a_share_bias")) +
                   '</p><p>' + safe(analysis.get("a_share_outlook")) + '</p><ul>' + sectors +
                   '</ul><p><strong>风险：</strong>' + safe("；".join(analysis.get("risks", []))) +
                   '</p><div class="small">分析时间：' + safe(analysis.get("generated_at_utc")) +
                   ' · 不确定性：' + safe(analysis.get("uncertainty")) + '</div></div>')
        sources = analysis.get("evidence_urls", [])
        evidence = "<p class='small'>研判参考：" + " · ".join(
            f'<a href="{safe(u)}" target="_blank" rel="noopener noreferrer">来源 {i+1}</a>'
            for i, u in enumerate(sources) if isinstance(u, str) and u.startswith("https://")) + "</p>"
    else:
        summary = '<div class="notice">分析尚未更新：当前页面仅包含自动采集的行情与新闻标题，不能据此推断新闻导致涨跌。</div>'
        outlook = '<div class="card"><p>等待人工或模型核验事实后补充盘前研判。请勿把未核验的 RSS 标题当作事件因果。</p></div>'
        evidence = ""
    body = ('<p class="sub">报告日期（北京时间）：' + safe(date) + ' · 生成时间（UTC）：' +
            safe(data.get("collected_at_utc")) + '</p><h2>01 / 关键市场数据</h2>' + cards +
            '<h2>02 / 全量监测指标</h2>' + table + '<h2>03 / 市场解读</h2>' + summary +
            '<h2>04 / 近期国际新闻（RSS 标题，未经独立核验）</h2>' + news_html +
            '<h2>05 / A股开盘前研判</h2>' + outlook + evidence +
            '<h2>06 / 数据质量</h2><div class="card"><p class="small">可用行情 ' +
            str(sum(q["status"] == "ok" for q in data.get("quotes", []))) + '/' +
            str(len(data.get("quotes", []))) + '；新闻 ' + str(len(data.get("news", []))) +
            ' 条；所有行情与判断都应附可核对时间和来源。更新历史文件不会覆盖原始日报。</p></div>')
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
