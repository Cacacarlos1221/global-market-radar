# Global Market Radar · 全球市场雷达

> A reproducible, evidence-aware daily research log for AUD exchange rates, US equities, global macro news and the next A-share session.

[最新晨报](https://Cacacarlos1221.github.io/global-market-radar/) · [历史归档](reports/archive.html) · **[HTML 晨报规范](docs/REPORT_SPEC.md)** · [数据字典](docs/DATA_DICTIONARY.md) · [架构](docs/ARCHITECTURE.md) · [运维手册](docs/OPERATIONS.md)

## 项目目标

将“每天 08:30 阅读全球市场晨报”扩展为可追溯、可分析、可复用的金融数据研究仓库：

- **行情事实层**：AUD/CNY、AUD/USD、纳指、标普500、道指、美元、原油、黄金、美债及A股指数；保留数据观察时间和前一可比交易日参考值。
- **事件证据层**：保留重要新闻标题、来源、发布时间、链接和核验状态；不能把新闻同时发生误写成因果关系。
- **分析判断层**：每天可以追加结构化的国际市场解读、A股行业影响假设、风险与证据引用；不制造无法核实的结论。
- **研究资产层**：HTML 日报、JSON 原始快照、CSV 历史台账及可复用 Python 脚本，后续可直接开展相关性、事件研究、判断复盘。

## 当前自动化能力

| 能力 | 机制 | 状态 |
| --- | --- | --- |
| 每天获取公开行情和 RSS 新闻 | GitHub Actions，UTC 00:15（北京时间 08:15）触发 | 已配置，待首次运行核验 |
| 生成当天和历史 HTML | Python 标准库离线渲染 | 已实现 |
| 当日行情/新闻持久化 | 不覆盖的逐日 JSON 快照 + 去重 CSV | 已实现 |
| 自动分析国际新闻与A股影响 | 外部定时分析任务追加 JSON 后自动重渲染 | 接口已预留；依赖任务执行 |
| 免费静态网站 | GitHub Pages，main 分支根目录 | 需要在 Settings → Pages 启用 |
| 单元测试 | GitHub Actions / Python unittest | 已配置 |

**重要边界**：当前自动采集使用 Yahoo Finance 非官方行情接口和 Google News RSS，稳定性、授权与准确性不保证。**RSS 标题不是已核实事实，也不是股价因果证据**。结构化分析必须有来源；没有分析时 HTML 明确展示“待补充”，绝不凭空捏造。

GitHub Actions 的定时运行可能排队延迟，08:15 是触发目标，不是交付 SLA。既有 ChatGPT 08:30 晨报与仓库数据采集是两个任务，不应假设内容自动一致；分析 JSON 是两者对齐的接口。

## 目录导航

```text
global-market-radar/
├── .github/workflows/
│   ├── daily.yml               # 每日拉取、重渲染、自动提交
│   └── tests.yml               # 自动单元测试
├── config/instruments.json     # 指标表、单位与行情源
├── scripts/
│   ├── sources.py              # 公开行情 / RSS 适配器
│   ├── pipeline.py             # 不覆盖快照、CSV 去重、HTML 构建
│   ├── render.py               # 静态网页主题
│   └── stats.py                # CSV 历史数据统计工具
├── data/
│   ├── daily/YYYY/MM/DD.json   # 每日完整原始事实快照
│   ├── analysis/YYYY/MM/DD.json # 经过核验的分析（可选）
│   └── history/
│       ├── quotes.csv          # 按报告日+资产唯一
│       └── events.csv          # 按报告日+事件唯一
├── reports/
│   ├── archive.html            # 历史索引
│   └── YYYY/MM/DD.html         # 当日网页
├── docs/                       # 架构、字段字典、维护规范
├── tests/                      # 无外网依赖的单元测试
└── index.html                  # 最新晨报固定入口
```

## 本地运行

Python 3.11+，核心工具只使用标准库，不需要付费行情 API。

```bash
python -m unittest discover -s tests -v
python -m scripts.pipeline --render-only
python -m scripts.pipeline                       # 联网采集今天的行情并生成日报
python -m scripts.stats --asset AUD_CNY --days 90
python -m scripts.stats --asset AUD_CNY --compare NASDAQ --days 90
```

每日快照首次生成后不允许同日期覆盖，防止后来的行情回填悄悄改变原始研究记录。若采集失败，可在问题修复后按运维手册进行显式重采集或新版本修订，不能伪造或静默覆写。

## 分析数据如何接入

将遵循 [分析字段规范](docs/DATA_DICTIONARY.md) 的 JSON 写入 `data/analysis/YYYY/MM/YYYY-MM-DD.json`，推送后 GitHub Actions 会针对保留的每日快照重新渲染 HTML。分析写入应包括明确的事实、解释与假设，且必须标明核验程度与来源链接。

## 注意事项

1. 市场休市时，最近可用收盘价的 market_date 可能早于报告日期；这不是“当天涨跌”。
2. AUD/CNY 与 AUD/USD 不是银行结汇价；不同来源与时点不能直接比较。
3. 美国十年期国债收益率 `^TNX` 为 Yahoo 的缩放指数（收益率百分数约乘以 10），**不直接等于收益率数值**。
4. A股“偏多/偏空”只是一项盘前待检验假设；不可把它写成已经发生的走势。
5. 仓库是公开的，请勿提交 API Key、个人账户、券商交易记录或非公开信息。
6. 本项目仅供个人学习、研究与信息整理，不构成投资建议。

请参阅 [运维说明](docs/OPERATIONS.md) 了解启用 Pages、手动运行工作流、缺失数据处理和故障排查。

## 2026-11 版式升级（04/06）

- **03 昨夜市场走势与原因**：价格变化和可能的驱动；**04 国际重要新闻综述**：模型筛选3–5项（最多6项）经过来源核验的重要事件，概括事实、影响和不确定性；**05 A股盘前研判**：前瞻判断。
- **06 新闻来源与参考资料**：引用来源集中列出并与04的每项事件双向关联；未选中的 RSS 线索折叠留存。
- 原来的**06 数据质量**缩到页脚，详细信息仍在 data/daily 的每日快照。旧版 analysis JSON 可正常渲染，缺少新闻综述时会显示待补充，不会自动从原始标题编造综述。
- 结构化字段 `news_digest` / `news_sources` 见 [数据字典](docs/DATA_DICTIONARY.md)。
