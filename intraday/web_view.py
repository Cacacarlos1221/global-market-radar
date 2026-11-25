"""Render the private, responsive radar dashboard from the latest snapshot."""
from html import escape
from math import isfinite


def display(value):
    return escape(str(value)) if value is not None else "—"


def numeric(value):
    return value if isinstance(value, (int, float)) and isfinite(value) else None


def decimal(value):
    value = numeric(value)
    return f"{value:.2f}" if value is not None else "—"


def render(snapshot, state, label, archives):
    stocks = snapshot.get("stocks", [])
    changes = [value for s in stocks if (value := numeric(s.get("change_pct"))) is not None]
    scale = max((abs(value) for value in changes), default=0) or 1
    rows = []
    for stock in stocks:
        pct = numeric(stock.get("change_pct"))
        direction = ("up" if pct > 0 else "down") if pct else ""
        move = "—" if pct is None else f"{pct:+.2f}%"
        bar = f'<span class="bar" aria-hidden="true"><i class="{direction}" style="width:{abs(pct)/scale*50:.2f}%"></i></span>' if pct else ""
        score = numeric(stock.get("score"))
        quality = {"ok":"正常", "missing":"无行情", "incomplete":"数据缺口", "stale":"已过期", "fetch_error":"采集失败"}.get(stock.get("status"), "待确认")
        rows.append(f'<tr><th scope="row">{display(stock.get("name"))}<small>{display(stock.get("code"))} · {quality}</small></th>'
                    f'<td>{decimal(stock.get("price"))}</td><td><span class="change {direction}"><span>{move}</span>{bar}</span></td>'
                    f'<td>{decimal(stock.get("vwap"))}</td><td>{decimal(stock.get("relative_volume"))}</td><td>{display(score)}</td></tr>')
    cards = [("自选股", len(stocks)), ("上涨", sum(v > 0 for v in changes)), ("下跌", sum(v < 0 for v in changes)),
             ("分钟数据正常", sum(s.get("status") == "ok" for s in stocks))]
    stats = "".join(f'<div class="card stat"><span class="muted">{name}</span><strong>{value}</strong></div>' for name, value in cards)
    archive_cards = []
    for kind, title, paths in archives:
        links = "".join(f'<li><a href="/{kind}/{p.name}">{display(p.stem.replace("_", " · "))}</a></li>' for p in paths)
        archive_cards.append(f'<section class="card"><h2>{title}</h2>' + (f'<ul class="records">{links}</ul>' if links else '<p class="muted">暂无记录</p>') + '</section>')
    note = "历史验收快照" if state["snapshot_phase"] == "historical" else "最近行情快照"
    warning = '<p class="pill warn">磁盘可用空间低于 5 GiB</p>' if state["low_disk"] else ""
    tone = "live" if state["state"] in ("live", "closing") else "warn" if state["state"] in ("stale", "interrupted") else ""
    table = ('<div class="table-wrap" tabindex="0" role="region" aria-label="自选股行情表"><table><thead><tr>'
             '<th scope="col">股票</th><th scope="col">现价</th><th scope="col">涨跌幅</th><th scope="col">VWAP</th>'
             '<th scope="col">量比</th><th scope="col">评分</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>') if rows else '<p class="muted">等待首个行情快照。</p>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">
<title>GMR 盘中雷达</title><link rel="stylesheet" href="/radar.css"></head><body><main>
<nav aria-label="数据接口"><span class="brand">GLOBAL MARKET RADAR</span><span><a href="/status.json">系统状态</a>　<a href="/latest.json">行情 JSON</a></span></nav>
<header class="hero"><div class="eyeline"><span role="status" class="pill {tone}">{display(label)}</span><span class="muted">{note}</span></div>
<h1>盘中雷达</h1><p class="muted">行情日期 {display(state["market_day"])} · 更新时间（北京时间）{display(state["snapshot_time"])}</p>{warning}</header>
<section class="stats" aria-label="自选股概览">{stats}</section>
<section class="card"><h2>自选股行情</h2>{table}</section><div class="grid">{''.join(archive_cards)}</div>
<footer>评分为实验指标，仅供研究。页面每 60 秒刷新。</footer></main></body></html>'''.encode()
