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
| observed_at_utc | 上游最新 K 线时间戳，UTC ISO 8601 |
| value_kind | daily_close 或 intraday_observation |
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
