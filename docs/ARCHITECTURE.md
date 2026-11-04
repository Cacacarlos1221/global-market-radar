# Architecture | 设计与数据生命周期

## 设计原则

1. Fact / Evidence / Interpretation 三层分离。事实来自带时间戳的行情数据，事件来自有来源的新闻标题，判断来自独立的分析文件。
2. 原始日报 JSON 是 append-only 的“时点快照”，用于还原当时的认知；数据表派生自该快照。
3. 同一报告日的行情必须记录交易所所属日期、UTC数据时间和比较基准；不得混同“今天”和“上一交易日”。
4. 任何失联或缺失值用 null/status=unavailable，绝不以零填充，更不猜测价格。
5. 报告 HTML 是衍生物，可随分析补充而重新生成；行情快照不会因此改写。
6. 历史数据适合研究，但行业因果推断需要控制混杂因素与使用严格的时间切分。

## 工作流

```text
GitHub Actions UTC 00:15
     │
     ├── Yahoo Finance chart API ──→ 价格 + UTC观测时间 + 市场日期
     └── Google News RSS ─────────→ 标题 + 来源 + 发布时刻 + 链接
                 │
         scripts.pipeline.collect
                 │
     ├── data/daily/YYYY/MM/YYYY-MM-DD.json  (不可静默覆写)
     ├── data/history/quotes.csv             (报告日+资产去重)
     └── data/history/events.csv             (报告日+事件ID去重)
                 │
          scripts.pipeline.render_all
                 │
     ├── reports/YYYY/MM/YYYY-MM-DD.html
     ├── reports/archive.html
     └── index.html
                 ▲
     data/analysis/YYYY/MM/YYYY-MM-DD.json (外部分析器追加)
                 │
         push触发 render-only 构建
```

## 数据科学用途（计划）

- FX 与美股同期相关性、滚动相关性以及带滞后项的相关分析。
- 宏观事件窗口研究：事件首次发生时刻与后续 N 个交易日回报，控制假期与时区。
- A股盘前判断验证：冻结预测方向、行业、时点，盘后用独立行情计算方向命中率、收益分布和基线比较。
- 新闻去重、可信度与影响机制归因：先有证据，再建立假设；不把 RSS 列表当新闻事实真值。
- 未来较大数据量可导出 Parquet + DuckDB；现阶段 JSON/CSV 足够，避免过度工程化。

## 延迟、重试、版本

GitHub scheduled workflows 是 best effort。若行情接口限流，当日可能只有缺失记录或历史收盘；不能替代低延时交易所行情。

每日事实快照一经提交不重采集覆盖：用后续版本明确标记修订原因、原始快照关联与时间。分析 JSON 可以补充或改写，但须保留 Git 历史。异常数据不得通过手工“修正”成未经验证的数字。

## 访问与部署

GitHub Pages 可展示 main 根目录的 index.html，直接访问 reports/archive.html 和每个日报页面。无需 Web 服务、数据库或云密钥。GitHub App 或模型自动写入 analysis JSON 后，push 触发只渲染已有快照，不抓取新价格。

## A股盘后复盘流水线

- 盘前09:30前：data/analysis + config/sector_watchlist.json → data/forecasts（append-only）。
- 盘后15:30：close.yml / GPT 总控 → 同日沪深300日K门禁 → 东方财富板块列表及沪深个股同日收盘K线 → data/close（append-only）。
- GPT 独立核验盘中新闻、解释行情偏差 → data/close_analysis（版本由Git维护） → scripts.close_review --render-only → reports/close/index.html + 每日HTML + archive。
- scripts.close_review --check 验证收盘快照、分析与页面一致性，GPT 再检查 GitHub Pages 实际部署。

原始晨报每个板块条目为一个判断样本，组合子板块等权观察但不可拆开增加预测次数。全部子板块均有同一交易日、语义严格匹配的指数才可进行组合评分；任何代理指数不混入命中率。盘后新发现热点不计入盘前指标。未核实 RSS 标题只能作为线索。

## 盘后观察与正式评分解耦（2026-11-04）

收盘行情与盘后分析属于主流程，冻结预测仅是统计评分可选输入。冻结存在 -> 原有严格评分；未冻结但有09:30前晨间报告 -> 非评分晨间主题走势对照；无可靠晨报 -> 固定池非评分观察。三者都必须尽力采集同日行情与盘中事件证据。forecast_status 只影响评分能力，不应决定报告能否发布。
