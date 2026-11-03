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

以上示意文本不是实际投资研判。建议 bias 取 positive/negative/mixed/watch，uncertainty 取 high/medium/low，evidence_urls 应是当日真实且可访问的来源，不要杜撰链接。对分析的变更通过 Git commit 保留审计轨迹。

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
