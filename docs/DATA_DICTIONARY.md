# Data Dictionary | 字段及口径

## data/daily/YYYY/MM/YYYY-MM-DD.json

- `schema_version`：目前 1.0。
- `report_date`：北京时间晨报日期（不是行情所属交易日）。
- `report_timezone`：Asia/Shanghai。
- `collected_at_utc`：实际采集时刻（UTC ISO 8601）。
- `quotes[]`：每项一条资产最新观测。
- `news[]`：新闻 RSS 条目，非核验新闻事实。
- `source_errors`：失败源信息；缺失时保持透明。
- `limitations[]`：数据质量限制。

## quotes[] 与 data/history/quotes.csv

CSV 增加 `report_date`；按 (`report_date`, `asset_key`) 去重。

| 字段 | 定义 |
| --- | --- |
| asset_key / key | 内部稳定资产编号（AUD_CNY、NASDAQ 等） |
| symbol | 上游行情代码 |
| category | fx / us_index / cn_index / macro |
| unit | 比价单位、指数点数或数据提供方原生单位 |
| market_date | 上游报价所在市场的日期（不等于 report_date） |
| observed_at_utc | 上游返回的 K 线时间戳，UTC ISO 8601，**日线通常对应K线起始时间而不是收盘成交时间** |
| value_kind | daily_close（交易时段已结束）、daily_bar_live（当前交易时段可能未结束）、daily_bar（仅为最近日线不保证已结算）、intraday_observation（最新盘中观测） |
| value | 当前最新有效观测值；缺失为 null / CSV空值 |
| reference_close | 上一个可用日线基准值 |
| reference_date | 上一个可用日线基准对应的市场日期 |
| change_pct | (value / reference_close - 1) × 100，单位百分比 |
| status | ok / unavailable |
| source | 数据源与性质 |
| error | 获取失败原因（仅日报 JSON） |

**特别说明**：FX 最新小时观测可能尚未收盘，因此 change_pct 是“对上个可用日线参考值的变化”，不应无条件称为昨天收盘涨跌。日线值可能有盘中未完结 K 线；这个项目只把上游数据按实际标识保存，不提供交易所官方结算价。节假日展示最近一交易日，必须同时展示 market_date。

## news[] 与 data/history/events.csv

- `event_id`：由新闻链接和标题哈希得到，便于去重。
- `topic`：macro / geopolitics / china / australia。
- `published_at_utc`：RSS 提供的发表时间，UTC。
- `headline`：新闻源标题，不能等价于真实事件已经核验。
- `source`、`url`：引用的源名称与新闻链接。
- `verification`：固定为 rss_headline_unverified，不能当作经过事实核查。

## data/analysis/YYYY/MM/YYYY-MM-DD.json

外部分析器追加该文件，不应冒用自动行情采集结果。建议结构：

```json
{
  "report_date": "YYYY-MM-DD",
  "generated_at_utc": "ISO-8601 UTC timestamp",
  "market_summary": "最重要的跨市场变化与可信的驱动解释",
  "a_share_bias": "mixed",
  "a_share_outlook": "今日A股盘前条件性推演，非既成事实",
  "a_share_sectors": [
    {"sector": "半导体", "bias": "watch", "reason": "列明证据与不确定性"}
  ],
  "risks": ["关键经济数据发布", "海外行情变化"],
  "uncertainty": "medium",
  "evidence_urls": ["https://example.org/source"]
}
```

以上示意文本不是实际投资研判。建议 bias 取 positive/negative/mixed/watch/neutral，uncertainty 取 high/medium/low，evidence_urls 应是当日真实且可访问的来源，不要杜撰链接。对分析的变更通过 Git commit 保留审计轨迹。

## 时间对齐与后验验证

- 北京 08:30 的 A股盘前判断，可能对应前一美股交易日结束后的市场反应。
- 盘后验证必须选对应的 `target_trade_date`，不允许以报告日简单 join 美股日线。
- 高质量分析需保存预测产生时间、可用信息截止点、行业/指数标的及真实后验，用于防止未来信息泄漏。
- 原始数据与版本应长期保留；研究导出不要修改作为审计证据的日快照。

## 已知的 2026-11-03 测试数据口径说明

当天首次快照于北京时间14:44生成，来源数据曾使用 daily_close 标注当时尚在交易的A股日线。原始快照遵循不可覆盖原则保留；此后生成的快照已在代码层区分 daily_bar_live。US10Y 的 ^TNX=4.894 是雅虎显示的 10年期美债收益率 4.894%，不是 48.94%，早期配置的“×10”描述已修正。该资产的 change_pct 为收益率数值的相对百分比变化，并非基点变化；分析利率时更应该比较绝对百分比差（乘100得到bps）。

## 国际重要新闻综述 news_digest / news_sources（2026-11 起）

第 04 节呈现经过筛选、核验、归纳的新闻综述；第 06 节呈现分析引用及**默认折叠**的所有原始 RSS 新闻线索。原始 data/daily 快照与 events.csv 不会因过滤展示而改变。

可在 data/analysis/YYYY/MM/YYYY-MM-DD.json 中新增以下字段（原 market_summary / a_share_* / evidence_urls 仍兼容）：

```json
{
  "news_digest": {
    "overview": "综合最近24小时核心事件的市场主线，避免复述03行情",
    "items": [
      {
        "title": "经过核验的事件标题",
        "summary": "事实、时间与已经确认的信息",
        "market_impact": "可能影响哪些资产；说明机制与因果不确定性",
        "importance": "high",
        "source_ids": ["S1"]
      }
    ]
  },
  "news_sources": [
    {
      "id": "S1",
      "title": "来源报道标题",
      "publisher": "发布机构",
      "published_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
      "url": "https://真实新闻来源网址",
      "verification": "reported"
    }
  ]
}
```

**要求**：条数按当日新闻决定，通常3–5条、最多6条；不为凑数量制造事件。每个 item 必须提供 title、summary、market_impact，并在 source_ids 引用至少一个具有有效 HTTPS 地址的 news_sources.id；无来源的内容不能被写成已核实事件。news_sources 中 publisher、发布时间与 verification 应如实记录，只有实际阅读过相应报道时才可把核验程度提高。使用“据媒体报道”“可能影响”等标识不确定性。生成器校验新格式的引用一致性；若无 digest，04 明确标记待补充，06 仍能展示原始线索。旧版 evidence_urls 在06列为历史分析参考，不静默删除。

**区分03/04/05**：03解释已发生的资产价格变化；04介绍重要事件及其可能的市场影响；05提出A股盘前条件性研判。避免复述和未来信息泄漏。

**数据质量**：原06不再单独占据章节，缩为页面底部状态行；采集失败原因、资产状态、所有RSS依旧保存在 JSON 中供审计。

## USD/CNY 监测指标及历史兼容

- `USD_CNY`：美元兑人民币，Yahoo Finance `CNY=X`，`category=fx`，`unit=CNY/USD`，报价含义 **1 USD = N CNY**。
- 此项列为首页第 1 张行情卡片；`AUD_USD` 移到第 6 张卡片，详细行情表按采集指标顺序展示。
- 新增监测指标从下一次正式成功采集开始记入当日 `quotes[]` 与历史 `quotes.csv`，不追溯改写此前不可变的原始快照。早期 HTML 展示缺失提示，不能当作 0 汇率。

## Bias 五类倾向标签（2026-11）

正式取值为 `positive`（偏利好）、`negative`（偏利空）、`mixed`（多空交织）、`watch`（重点观察、信息不足）、`neutral`（中性、已评估影响有限）。`watch` 不是 `mixed`，也不是 `neutral`。网页由 `scripts/render.py` 按五类固定映射渲染颜色块，未知值显示“未分类”。统一定义、色彩和其他术语见 [README：报告术语与标签定义](../README.md#报告术语与标签定义统一规范)。历史分析无需补写字段；不改动原始判断。

## 盘后复盘事实与验证口径

- data/forecasts/YYYY/MM/YYYY-MM-DD.json：盘前预测冻结时间、原始 a_share_sectors、晨间分析 SHA256、同步冻结的 watchlist 配置；09:30后禁止补冻。
- data/close/YYYY/MM/YYYY-MM-DD.json：report_date、captured_at_utc、market_date、source、benchmark.quote（沪深300）、predicted_groups、hot_sectors、news_clues、warnings。行情日与报告日不一致则不可评分。
- predicted_groups[]：保留晨报原始一条判断。components[] 含实际板块名/代码/来源、同日 quote、预选 stocks、is_proxy 标志。aggregated_change_pct 为所有可评分成分板块日涨跌幅的等权均值；任一缺失或代理则 null。
- excess_vs_csi300_pct = aggregated_change_pct - 沪深300收盘涨跌幅，单位百分点。direction_hit：Positive且聚合涨幅>0为true，Negative且聚合涨幅<0为true；方向相反false；零涨幅、无有效指数、代理板块和其他标签均为null，不计准确率分母。
- hot_sectors[]：仅限盘后自动发现，独立展示，不参与命中率。
- data/close_analysis/YYYY/MM/YYYY-MM-DD.json：report_date、generated_at_utc、summary、key_findings[]、attributions[]、new_events[]、next_watch[]、news_sources[]。news_sources 为带可用HTTPS来源链接的引用目录；new_events 必须引用至少一项来源，不能以收盘后发表的消息反推盘中行情原因。
- reports/close/index.html、reports/close/archive.html 和 reports/close/YYYY/MM/YYYY-MM-DD.html：仅展示有收盘快照、GPT盘后分析的记录。

盘后板块/个股接口为东方财富非官方公开行情源，可能延迟、变化或限流；板块无法严格匹配时标记 unavailable，不能凭想象填涨跌幅。

## 无冻结盘后观察口径（v1.1）

data/close 中 forecast_status 约定为 frozen、morning_analysis_unfrozen、watchlist_only；后两种只作观察，direction_hit=null。缺冻结时仍可由晨报 data/analysis 匹配当日主题（必须提供可信且早于09:30的分析时间），或退化为配置的固定行业池。morning_analysis_sha256 仅证明盘后使用的晨报文件内容，不代表盘前冻结证据。observed_close_instruments 记录同日报价成功的观察条目数量。基准指数不存在时超额收益为 null、如实标注；仍可做其他同日价格及新闻总结。

## 数据质量补充：stale（2026-11-05）

`quotes[].status` 可取 `ok / unavailable / stale`，其中 `stale` 代表**获取到数值但该交易日期明显落后于同市场其他指数**，不可以与最新数据同等看待。该字段不表示该数值本身为零或无效；分析和报告必须核对 `market_date` 与 `error`。东财优先源为非官方公开API，来源记录于 `source` 和可选 `source_url`；日K无可靠实际取样时间则 `observed_at_utc=null`，不可造 UTC 收盘时刻。历史回补通过 data/supplements 的 source_correction 单独保留来源及时间，不改写原始 data/daily。
