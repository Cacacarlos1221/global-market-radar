"""盘后可审计 HTML：行情事实、原始预判与后验新闻严格分层。"""
from datetime import datetime, timezone
from html import escape
from .render import shell, safe, bias_tag, valid_url, beijing_time

def pct(value, suffix="%"):
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:+.2f}{suffix}"

def amount(value):
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"

def colour(value):
    return "up" if isinstance(value, (int, float)) and value > 0 else "down" if isinstance(value, (int, float)) and value < 0 else "muted"

def cite_refs(item, catalog):
    return " ".join(f'<a class="cite" href="#close-ref-{safe(sid)}">[{safe(sid)}]</a>'
                    for sid in item.get("source_ids", []) if sid in catalog)

def validate_close_analysis(data):
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("close analysis summary required")
    for name in ("key_findings", "attributions", "new_events", "news_sources", "next_watch"):
        if not isinstance(data.get(name, []), list):
            raise ValueError(name + " must be a list")
    sources = {}
    for item in data.get("news_sources", []):
        sid = item.get("id")
        if (not isinstance(sid, str) or not sid.isidentifier() or sid in sources
                or not valid_url(item.get("url"))):
            raise ValueError("invalid/duplicate news source id or HTTPS URL")
        sources[sid] = item
    for name in ("key_findings", "attributions", "new_events"):
        for i, item in enumerate(data.get(name, [])):
            if not isinstance(item, dict):
                raise ValueError(name + " element must be object")
            refs = item.get("source_ids", [])
            if not isinstance(refs, list) or any(ref not in sources for ref in refs):
                raise ValueError(f"{name}[{i}] has invalid source_ids")
            if name == "new_events" and not refs:
                raise ValueError(f"{name}[{i}] news must have verified sources")
            if name == "attributions" and item.get("causal_status") == "confirmed" and not refs:
                raise ValueError(f"{name}[{i}] confirmed attribution requires evidence")
    return True

def stock_table(stocks, legend):
    if not stocks:
        return '<p class="small">未配置或未获取到可比的代表个股。</p>'
    rows = []
    for stock in stocks:
        status = stock.get("status")
        q = stock.get("change_pct") if status == "ok" else None
        rows.append('<tr><td>' + safe(stock.get("name")) + ' <span class="small">' + safe(stock.get("code")) +
                    '</span></td><td class="' + colour(q) + '">' + pct(q) +
                    '</td><td>' + amount(stock.get("close")) + '</td><td>' +
                    safe(stock.get("market_date")) + '</td></tr>')
    return ('<p class="small">' + safe(legend) +
            '；日涨幅以相同标的上一交易日收盘价计算；未获取同日K线的记录不参与比较。</p>'
            '<div class="table-wrap"><table><thead><tr><th>股票</th><th>日涨跌</th><th>收盘价</th><th>交易日</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')

def forecast_verdict(group, frozen):
    """Never treat an observation label as a directional hit or a market-data failure."""
    if not frozen:
        return "仅供观察（未冻结）"
    if group.get("bias") in ("mixed", "watch", "neutral"):
        return "非方向研判（不计命中率）"
    hit = group.get("direction_hit")
    if hit is True:
        return "方向一致"
    if hit is False:
        return "方向偏离"
    components = group.get("components", [])
    if any(x.get("is_proxy") for x in components):
        return "代理指数不计分"
    return "缺完整同名指数（待评分）"

def observation_overview(groups, benchmark, frozen):
    """One glance at *every* frozen opinion, independent of strict scoring."""
    market_date = benchmark.get("market_date")
    benchmark_pct = benchmark.get("change_pct") if benchmark.get("status") == "ok" else None
    rows = []
    for group in groups:
        components = []
        for item in group.get("components", []):
            q = item.get("quote") or {}
            if q.get("status") != "ok" or q.get("market_date") != market_date:
                continue
            change = q.get("change_pct")
            if not isinstance(change, (int, float)):
                continue
            title = item.get("board_name") or item.get("name")
            proxy = "（代理）" if item.get("is_proxy") else ""
            extra = (round(change - benchmark_pct, 4)
                     if isinstance(benchmark_pct, (int, float)) else None)
            components.append(safe(title) + proxy + " <span class=\"" + colour(change) + "\">" +
                              pct(change) + "</span>（超额" + pct(extra, "个百分点") + "）")
        value = "；".join(components) if components else "暂无严格对应的当日板块指数"
        rows.append("<tr><td>" + safe(group.get("sector")) + "</td><td>" +
                    bias_tag(group.get("bias")) + "</td><td>" + value +
                    "</td><td>" + safe(forecast_verdict(group, frozen)) + "</td></tr>")
    return ('<div class="table-wrap"><table><thead><tr><th>盘前关注主题</th>'
            '<th>冻结标签</th><th>当日板块表现与相对沪深300</th><th>方向评分状态</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
            '<p class="small">说明：Positive/Negative 才有明确涨跌方向；Mixed、Watch、Neutral '
            '不是上涨或下跌预测，仍逐项对照收盘表现。代理指标可观察，但不可冒充原主题。'
            '方向一致率只统计真正有方向、且获得同日严格对应指数的研判；不能把1/1理解成8/8。</p>')

def predicted_card(group, benchmark=None):
    direction = group.get("direction_hit")
    status = forecast_verdict(group, group.get("evaluation") != "unfrozen_observation")
    delta = group.get("aggregated_change_pct")
    benchmark = benchmark or {}
    benchmark_pct = benchmark.get("change_pct") if benchmark.get("status") == "ok" else None
    benchmark_date = benchmark.get("market_date")
    parts = []
    for item in group.get("components", []):
        quote = item.get("quote", {})
        change = quote.get("change_pct") if quote.get("status") == "ok" else None
        proxy = ' · 代理主题（仅用于观察，不参与命中率）' if item.get("is_proxy") else ''
        excess = (round(change - benchmark_pct, 4)
                  if isinstance(change, (int, float)) and isinstance(benchmark_pct, (int, float))
                  and quote.get("market_date") == benchmark_date else None)
        excess_note = ('<span class="' + colour(excess) + '"><strong>' + pct(excess, " 个百分点") +
                       '</strong></span>' if excess is not None else '—（缺少同日可比指数）')
        parts.append('<article class="news-card"><strong>' + safe(item.get("name")) +
                     '</strong> · 实际板块：' + safe(item.get("board_name")) + proxy +
                     '<div class="' + colour(change) + '"><strong>' + pct(change) + '</strong> '
                     '<span class="small">指数/板块 ' + safe(item.get("board_code")) +
                     ' · ' + safe(quote.get("market_date")) + '</span></div>' +
                     '<div class="small">相对沪深300：' + excess_note +
                     ' · 大盘当日涨跌 ' + pct(benchmark_pct) + '</div>' +
                     stock_table(item.get("stocks", []), "盘前预选的代表股") + '</article>')
    if not parts:
        parts = ['<div class="notice">盘前判断没有匹配的独立指数或股票池，保留原始观点但不纳入准确率。</div>']
    composite = ('<div class="grid"><div class="metric"><div class="label">组合板块等权涨跌</div>'
                 '<div class="value ' + colour(delta) + '">' + pct(delta) + '</div></div>'
                 '<div class="metric"><div class="label">对沪深300超额收益</div><div class="value ' +
                 colour(group.get("excess_vs_csi300_pct")) + '">' + pct(group.get("excess_vs_csi300_pct")) +
                 '</div></div></div>' if delta is not None else
                 '<p class="small">此组合不具备完整、同名的可比板块指数（或包含代理主题）；'
                 '不展示虚构的综合涨跌，下面按各子板块分别与沪深300比较。</p>')
    return ('<details open><summary>' + safe(group.get("sector")) + ' ' +
            bias_tag(group.get("bias")) + ' · ' + status + '</summary>' +
            '<div class="card">' + composite + '<p><strong>原始预测理由：</strong>' + safe(group.get("reason")) +
            '</p><p class="small">单个子板块可以独立观察超额涨跌；组合正式方向评分仍按冻结预测和有效指数规则计算。</p>' +
            "".join(parts) + '</div></details>')

def hot_card(board):
    quote = board.get("quote", {})
    change = quote.get("change_pct") if quote.get("status") == "ok" else None
    return ('<details><summary>' + safe(board.get("name")) + ' <span class="' + colour(change) +
            '">' + pct(change) + '</span></summary><div class="card"><p class="small">盘后发现：' +
            safe(board.get("board_type")) + ' · ' + safe(board.get("code")) +
            '；并非盘前预测，不能算预测正确。</p>' +
            stock_table(board.get("stocks", []), "盘后按板块涨幅筛选的活跃个股，不纳入预测命中") + '</div></details>')

def narrative(analysis):
    sources = {x["id"]: x for x in analysis.get("news_sources", [])}
    blocks = ['<div class="digest-overview"><strong>GMR · 盘后综合判断</strong><p>' +
              safe(analysis["summary"]) + '</p></div>']
    for item in analysis.get("key_findings", []):
        blocks.append('<article class="news-card"><h3>' + safe(item.get("title")) + '</h3><p>' +
                      safe(item.get("finding")) + '</p><div class="small">相关来源：' +
                      cite_refs(item, sources) + '</div></article>')
    if analysis.get("attributions"):
        blocks.append('<h3>盘前研判对照与可能的驱动因素</h3>')
        for item in analysis["attributions"]:
            blocks.append('<article class="news-card"><strong>' + safe(item.get("sector")) +
                          '</strong><p>实际表现：' + safe(item.get("observation")) +
                          '</p><p>解释与不确定性：' + safe(item.get("explanation")) +
                          '</p><div class="small">因果状态：' + safe(item.get("causal_status", "hypothesis")) +
                          ' · 参考来源：' + cite_refs(item, sources) + '</div></article>')
    if analysis.get("new_events"):
        blocks.append('<h3>盘中新增并核验的事件</h3>')
        for item in analysis["new_events"]:
            blocks.append('<article class="news-card"><strong>' + safe(item.get("title")) +
                          '</strong><p>' + safe(item.get("summary")) + '</p>' +
                          '<div class="small">发布时间：' + beijing_time(item.get("published_at_utc")) +
                          ' · 来源：' + cite_refs(item, sources) +
                          '</div></article>')
    blocks.append('<h3>后续跟踪</h3><div class="card"><ul>' +
                  "".join('<li>' + safe(x) + '</li>' for x in analysis.get("next_watch", [])) +
                  '</ul></div>')
    refs = []
    for sid, item in sources.items():
        refs.append('<li id="close-ref-' + safe(sid) + '"><strong>[' + safe(sid) + ']</strong> ' +
                    '<a href="' + safe(item["url"]) + '" target="_blank" rel="noopener noreferrer">' +
                    safe(item.get("title") or item.get("publisher") or item["url"]) +
                    '</a><div class="small">发布时间：' + beijing_time(item.get("published_at_utc")) +
                    ' · ' + safe(item.get("publisher")) + ' · 核验：' +
                    safe(item.get("verification", "reported")) + '</div></li>')
    blocks.append('<h3>新闻与证据来源</h3><div class="card"><ul class="source-list">' +
                  ("".join(refs) if refs else '<li>未引用可核验的新报道；无证据不做新闻归因。</li>') +
                  '</ul></div>')
    return "".join(blocks)

def render_close_report(raw, analysis, prefix="../../"):
    day = raw["report_date"]
    groups = raw.get("predicted_groups", [])
    evaluable = [x for x in groups if x.get("direction_hit") is not None]
    hits = sum(x.get("direction_hit") is True for x in evaluable)
    directional = sum(x.get("bias") in ("positive", "negative") for x in groups)
    quote = raw.get("benchmark", {}).get("quote", {})
    observable = sum(any(c.get("quote", {}).get("status") == "ok"
                         and c.get("quote", {}).get("market_date") == raw.get("report_date")
                         for c in g.get("components", [])) for g in groups)
    benchmark_move = quote.get("change_pct")
    frozen = bool(raw.get("forecast_sha256"))
    scope = raw.get("forecast_status", "frozen" if frozen else "watchlist_only")
    scope_text = {"frozen": "已冻结的盘前预测",
                  "morning_analysis_unfrozen": "晨间报告主题（无冻结，仅作观察）",
                  "watchlist_only": "固定跟踪池（未提供可核验晨报）"}.get(scope, "收盘观察")
    head = ('<p class="sub">交易日：' + safe(day) + ' · 收盘数据抓取：' +
            beijing_time(raw.get("captured_at_utc")) + ' · 盘前冻结时间：' +
            beijing_time(raw.get("forecast_frozen_at_utc")) + '</p>' +
            '<div class="report-stage">事实：同日可核验收盘K线 · 研究来源：' + safe(scope_text) +
            ' · 新闻：盘后另行核验。没有冻结不妨碍正常生成收盘观察与新闻总结。'
            '本页不是投资建议，板块数据源为非官方接口。</div>' +
            '<div class="grid"><article class="metric"><div class="label">今日跟踪主题组</div>' +
            '<div class="value">' + str(len(groups)) + '</div></article>' +
            '<article class="metric"><div class="label">有板块走势可观察</div><div class="value">' +
            str(observable) + '</div></article>' +
            '<article class="metric"><div class="label">明确方向判断</div><div class="value">' +
            str(directional) + '</div></article>' +
            '<article class="metric"><div class="label">严格可评分</div><div class="value">' +
            str(len(evaluable)) + '</div></article>' +
            '<article class="metric"><div class="label">方向一致（有效样本）</div><div class="value">' +
            (str(hits) + '/' + str(len(evaluable)) if evaluable else '不适用') + '</div></article>' +
            '<article class="metric"><div class="label">沪深300 日涨跌</div><div class="value ' +
            colour(benchmark_move) + '">' + pct(benchmark_move) + '</div></article></div>')
    if not frozen:
        head += ('<div class="notice">今天没有开盘前冻结记录，但板块、代表股及热门主题仍按真实收盘价格展示，'
                 '并继续提供盘后新闻研究。仅不计算严格预测命中率。</div>')
    if not evaluable:
        head += '<p class="small">严格预测命中率不适用；并不妨碍阅读今日市场观察。</p>'
    forecast_cards = "".join(predicted_card(x, quote) for x in groups) if groups else (
        '<div class="notice">没有可回溯的盘前板块记录。</div>')
    hot_cards = "".join(hot_card(x) for x in raw.get("hot_sectors", [])) or (
        '<div class="notice">今日热门板块暂无可靠收盘数据。</div>')
    clues = raw.get("news_clues", [])
    source_clues = '<details><summary>盘中新闻 RSS 原始线索（' + str(len(clues)) + '）</summary><div class="card">'
    for item in clues:
        url = valid_url(item.get("url"))
        if url:
            source_clues += '<p><a target="_blank" rel="noopener noreferrer" href="' + safe(url) + '">' + (
                safe(item.get("headline"))) + '</a> · <span class="small">' + (
                beijing_time(item.get("published_at_utc"))) + ' · 标题未经独立核验</span></p>'
    source_clues += '</div></details>'
    warnings = raw.get("warnings", [])
    quality = ('<div class="quality">原始行情：' + safe(raw.get("source")) + ' · 数据交易日 ' +
               safe(raw.get("market_date")) + ' · 行情异常项 ' + str(len(warnings)) +
               ' · 盘前冻结 SHA256 ' + safe(raw.get("forecast_sha256")) +
               '<details><summary>展开数据异常与局限</summary><ul>' +
               "".join('<li>' + safe(x) + '</li>' for x in warnings) +
               '</ul><p>数据缺失、非同日K线和代理板块不参与方向统计；'
               '未预测的热门板块另列，新闻同现不等于因果。</p></details></div>')
    body = (head + '<h2>01 / 晨间关注主题与收盘观察</h2>' +
            '<h3>全部盘前观点的收盘表现一览</h3>' +
            observation_overview(groups, quote, frozen) +
            '<h3>逐组研判理由、指数与代表股</h3>' + forecast_cards +
            '<h2>02 / 盘后发现的热门板块</h2><p class="small">仅展示新发现，不加入盘前预测命中率。</p>' +
            hot_cards + '<h2>03 / GMR 盘后复盘与新闻归因</h2>' + narrative(analysis) +
            '<h2>04 / 新闻检索线索与数据审计</h2>' + source_clues + quality +
            '<p class="small">分析生成：' + beijing_time(analysis.get("generated_at_utc")) + '</p>')
    return shell("A股盘后复盘 · " + day, body, prefix + "index.html")

def render_close_archive(days):
    items = "".join('<li><a href="' + safe(d[:4]) + '/' + safe(d[5:7]) + '/' +
                    safe(d) + '.html">' + safe(d) + '</a></li>' for d in sorted(days, reverse=True))
    return shell("盘后复盘历史", '<div class="card"><p>仅收录已完成盘后分析与HTML构建的交易日。</p><ul>' +
                 (items or "<li>暂无盘后复盘</li>") + '</ul></div>', "../../index.html")

def render_close_home(raw, analysis):
    if not raw:
        return shell("A股盘后复盘", '<div class="card"><h2>盘后页面已就绪</h2>'
                     '<p>首次取得可核验的当日收盘行情及 GMR 盘后分析后自动展示；未冻结预测也可正常生成收盘观察和新闻总结。</p>'
                     '<p><a href="archive.html">查看盘后历史归档</a></p></div>', "../../index.html")
    return render_close_report(raw, analysis, "../../")
