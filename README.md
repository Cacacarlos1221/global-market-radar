# Global Market Radar · GMR

> A reproducible, evidence-aware daily research log for AUD exchange rates, US equities, global macro news and the next A-share session.

[最新晨报](https://Cacacarlos1221.github.io/global-market-radar/) · **[盘后复盘](https://Cacacarlos1221.github.io/global-market-radar/reports/close/index.html)** · [晨报历史](reports/archive.html) · [盘后历史](reports/close/archive.html) · **[HTML 晨报规范](docs/REPORT_SPEC.md)** · [数据字典](docs/DATA_DICTIONARY.md) · [架构](docs/ARCHITECTURE.md) · [运维手册](docs/OPERATIONS.md)

## 项目目标

将“每天 08:30 阅读全球市场晨报”扩展为可追溯、可分析、可复用的金融数据研究仓库：

- **行情事实层**：USD/CNY、AUD/CNY、纳指、标普500、道指、AUD/USD、美元、原油、黄金、美债及A股指数；保留数据观察时间和前一可比交易日参考值。
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

## 报告术语与标签定义（统一规范）

以下定义是**本项目的定性研究口径**，适用于报告的总体倾向 \`a_share_bias\`、行业倾向 \`a_share_sectors[].bias\`，以及未来的回测和 Agent 输出。每日 HTML 用标签直接展示，不重复刊登本节说明。

### A 股市场与行业倾向（Bias）

| 原始值 | 中文显示 | 颜色 | 具体判定边界 |
| --- | --- | --- | --- |
| \`positive\` | **偏利好** | 🟢 绿色 | 有可追溯的积极催化，正向影响明显占优；不是保证上涨 |
| \`negative\` | **偏利空** | 🔴 红色 | 有可追溯的负面催化，负向影响明显占优；不是保证下跌 |
| \`mixed\` | **多空交织** | 🟣 紫色 | 同时存在实质性正负因素，或不同子行业方向分化，尚不能得出一致方向 |
| \`watch\` | **重点观察** | 🟡 琥珀色 | 有待关注的变量，但缺乏方向性证据、关键数据或触发条件；目前**不能可靠判断** |
| \`neutral\` | **中性** | ⚪ 灰色 | 已掌握的证据支持影响较小或大体平衡；与“缺数据而无法判断”的 watch 不同 |

**边界案例**：人民币走弱对部分出口商利好、对进口成本不利 → \`mixed\`；某一宏观事件存在但缺少价格与产业传导证据 → \`watch\`；多个充分核验的变量均显示对该行业影响有限 → \`neutral\`。

- 标签只代表**盘前信息条件下的相对影响方向**，不表示涨跌概率、收益幅度、投资评级或买卖建议。
- \`mixed\` ≠ \`watch\` ≠ \`neutral\`：分别是“多空并存”“证据不足”“有依据认为影响有限”。
- 颜色仅用于醒目区分，并且始终配有文字；不依赖单纯颜色传递含义。代码中的未知值显示“未分类”，**不会擅自归入 neutral**。
- 标签适用于总体市场及各行业，行业 \`positive\` 不代表整体市场也是 \`positive\`；写入 JSON 时统一使用小写英文值。

### 其他报告字段和常用术语

| 字段 / 标签 | 可能的值 | 约定含义 |
| --- | --- | --- |
| \`confidence\`（**后续预留**） | \`high / medium / low\` | 对**方向判断的证据支持程度**，与涨跌概率不同；当前尚未校准也不是必填字段 |
| \`uncertainty\` | \`high / medium / low\`，或带文字说明 | 分析的不确定性程度；**高不确定性不等于负面方向**。既有数据也可能写成 \`medium-high: ...\`，保留兼容 |
| \`importance\` | \`high / medium / low\` | 04 国际事件的重要程度，表示潜在影响与关注优先级，**不是走势方向** |
| \`verification\` | \`official / reported / rss_headline_unverified\` 等 | 证据的核验来源与级别。仅有 RSS 标题不得描述为经过独立核实 |
| \`status\`（行情） | \`ok / unavailable\` | 采集是否得到有效数值；\`ok\` **不保证最新**，还需检查行情日期和来源 |
| \`value_kind\` | \`daily_close / daily_bar / daily_bar_live / intraday_observation / official_daily_close\` | 日终收盘、日线、未完成日线、盘中观测、交易所官方收盘等不同报价类型 |
| \`report_date\` | 北京时间日期 | 本次晨报的报告日，不等于所有资产的交易日期 |
| \`market_date\` | 市场本地日期 | 上游行情所属交易日或 K 线日期，美股和 A 股可能不同 |
| \`observed_at_utc\` | UTC 时间戳 | 上游 K 线观测时间，**不一定是成交收盘时间** |
| \`change_pct\` | 百分比数值 | 相对 \`reference_close\` 的变化率；对收益率类资产应另留意基点（bp）含义 |
| \`source_ids\` | 如 \`S1 / S2\` | 第 04 节新闻摘要到第 06 节来源的对应编号 |

### 数据研究与准确率验证

后续研究可以将标签与盘后实际表现比对，但必须事先冻结 \`generated_at_utc\`、信息截点、行业标的和 \`target_trade_date\`，控制前视偏差。**当前标签还不是统计校准后的分类模型**，不应自行规定 \`positive = 上涨概率大于 60%\` 等不存在的阈值。若未来增加真实的置信度、概率或评分卡，需要另建指标定义和验证报告。

## 注意事项

1. 市场休市时，最近可用收盘价的 market_date 可能早于报告日期；这不是“当天涨跌”。
2. AUD/CNY 与 AUD/USD 不是银行结汇价；不同来源与时点不能直接比较。
3. 美债收益率字段使用数据源的对应收益率百分数口径，例如 `^TNX` 观测值 4.95 表示约 4.95%；换算基点变化时不要把同比涨跌幅直接当 bp。
4. A股“偏多/偏空”只是一项盘前待检验假设；不可把它写成已经发生的走势。
5. 仓库是公开的，请勿提交 API Key、个人账户、券商交易记录或非公开信息。
6. 本项目仅供个人学习、研究与信息整理，不构成投资建议。

请参阅 [运维说明](docs/OPERATIONS.md) 了解启用 Pages、手动运行工作流、缺失数据处理和故障排查。

## 2026-11 版式升级（04/06）

- **03 昨夜市场走势与原因**：价格变化和可能的驱动；**04 国际重要新闻综述**：模型筛选3–5项（最多6项）经过来源核验的重要事件，概括事实、影响和不确定性；**05 A股盘前研判**：前瞻判断。
- **06 新闻来源与参考资料**：引用来源集中列出并与04的每项事件双向关联；未选中的 RSS 线索折叠留存。
- 原来的**06 数据质量**缩到页脚，详细信息仍在 data/daily 的每日快照。旧版 analysis JSON 可正常渲染，缺少新闻综述时会显示待补充，不会自动从原始标题编造综述。
- 结构化字段 `news_digest` / `news_sources` 见 [数据字典](docs/DATA_DICTIONARY.md)。

## 2026-11 关键指标排序调整

顶部大指标现在固定为 **USD/CNY → AUD/CNY → NASDAQ → S&P 500 → Dow Jones → AUD/USD**。USD/CNY 采用 Yahoo Finance `CNY=X`，表示 **1 美元兑换多少人民币**；早于该字段上线的历史数据不进行伪造性补齐，完整布局规则详见 [REPORT_SPEC.md](docs/REPORT_SPEC.md)。

## 单指标缺失补采

可单独执行 `python -m scripts.backfill_quote --asset USD_CNY`，只获取当天缺失的美元兑人民币汇率，保存于 data/supplements 并合并到 HTML 与历史 CSV，不修改原始 JSON 快照。详见 [OPERATIONS.md](docs/OPERATIONS.md)。

## 单次总控、完整晨报发布机制（2026-11）

定时仓库维护任务以北京时间08:15为目标触发，负责检查 GitHub 数据采集、必要时通过 `data/requests/` 请求主动采集、输出经过核验的分析JSON并验收网页发布。GitHub仍保留定时兜底；数据采集不再主动发布分析尚未齐备的HTML。完整发布门禁为 `python -m scripts.release_check --date YYYY-MM-DD`，参考 [运维手册](docs/OPERATIONS.md)。不能保证定时任务无限期等待，失败必须报告。

## A股盘后复盘（2026-11）

新增北京时间 **15:30** 的盘后验证闭环，独立于实验 Agent 分支。

- [最新盘后复盘](reports/close/index.html)、[盘后历史](reports/close/archive.html) 和现有晨报共用 GitHub Pages。
- 盘前09:30前冻结原始方向判断、板块映射及预设代表股。多子板块的组合预测仅算一条样本；watch/mixed/neutral 与代理板块不硬算对错。
- 盘后收集行业/概念收盘指数、代表个股及热门板块，热门板块不计晨报预测命中率。新闻归因由GPT核实，并保留报道发布时间、来源、证据级别。
- GitHub Actions 定时采集由独立 ChatGPT 盘后总控监督；遇到休市、行情缺失和无法核验新闻，标注降级，不伪造当日结果。
- 实施细则见 [盘后实施与运维规范](docs/CLOSE_REVIEW.md)。
