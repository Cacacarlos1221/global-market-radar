# Operations | 日常运维

## 一次性设置（仓库所有者）

1. Settings → Pages → Build and deployment：选择 **Deploy from a branch**，Branch=main、Folder=/(root)，Save。生效后网页入口预计为 https://Cacacarlos1221.github.io/global-market-radar/ ，但在启用前可能返回 404。
2. Actions：确认 Workflow 已允许运行，仓库默认 Actions 策略未禁用。
3. Actions → Daily market data and HTML → Run workflow：可立即进行首次采集；观察日志内的成功/缺失行情。
4. 建议检查 Settings → Actions → General 的 Workflow permissions。工作流自带 `permissions: contents: write`，但组织策略仍可能阻止提交。
5. 每日 UTC 00:15（北京时间 08:15）尝试执行，GitHub 的定时任务可能延迟，不能保证 09:00 前交付。
6. ChatGPT 定时晨报与仓库自动采集**并非天然同一份数据**。维护任务应根据 data/daily 快照核验数据、填充 analysis JSON，并标注来源。

## 手动操作

```bash
python -m unittest discover -s tests -v
python -m scripts.pipeline                    # 今天采集+渲染；已存在快照会跳过采集
python -m scripts.pipeline --render-only      # 离线重渲染；改 analysis 后运行
python -m scripts.pipeline --date 2026-11-04  # 指定“报告日”，但仍抓当前数据，请勿用作历史回补
python -m scripts.stats --asset AUD_CNY --compare NASDAQ --days 60
```

**切勿**把指定过去日期的 `--date` 误当成历史行情回补：该参数只是报告日标识，数据永远是本次访问到的最新行情。过去日补录需要专门的 as-of 数据获取工具和证据。

## 失败与降级

- 价格 API 429 / 503：记录 status=unavailable 和 error；不填充虚构数据、不从其他时间段挪数据。
- 新闻 RSS 不可用：保留 source_errors、网页注明没有新闻。
- Git push 失败：检查 Actions 日志、保护分支、权限、是否发生并行冲突。
- 时区或交易日：核查 report_date、market_date、observed_at_utc 三列，先确认美股前一交易日是否休市。
- 分析任务缺失：HTML 展示“待补充”，不会自动拼凑市场原因。
- 已生成当日 snapshot：默认拒绝覆盖；缺失数据的修复需要后续版本化重采集（见 ARCHITECTURE.md），不可偷偷改写历史。

## 自动分析写入

将当日分析 JSON 写入 `data/analysis/YYYY/MM/YYYY-MM-DD.json`，文件日期必须等于内部 report_date。推送此文件后，GitHub Actions push 监听器自动 `--render-only` 重建 HTML。直接修改 HTML 可能在下次运行中被覆盖，应优先编辑分析 JSON。

## 数据风险

- 本仓库默认公开，严禁写入交易账户、API 密钥、内部业务资料。
- 免费公开接口可能有非商业用途或速率限制；确认服务条款再扩大调用量。
- 重要财经新闻应核验原始报道；自动 RSS 只是检索线索。
- 后续新增 backtesting 时需要冻结“盘前预测时间戳”，防止用盘后数据修正预测。

## 2026-11 新版06引用与04新闻综述

- 维护任务应在 `data/analysis/YYYY/MM/YYYY-MM-DD.json` 写入 `news_digest` 和 `news_sources`，每条摘要均附可追溯 source_ids。
- 不要将 RSS 标题自动总结成已核实事实；先阅读可信来源，确实核实后再给出事件摘要、市场影响和证据链接。若无法核实，保持04待补充。
- 新闻原始素材仍在 data/daily 和 data/history/events.csv 中，网页06默认收起原始 RSS 新闻列表；只要报告需要引用，可在 news_sources 中单独添加。
- 原06数据质量已移到页脚简要状态，错误仍按数据快照保留。历史分析缺少 news_digest 不会失败，只显示缺失提示。
- 只要更新 analysis JSON，现有 GitHub Actions 会 `--render-only` 更新 HTML；新格式的无效 source_ids 会使构建报错，需修正而不是删除引用。

## 缺失指标单独补采（2026-11）

- 日期已有原始快照时，普通日报采集不再修改它，新增指标会显示缺失。
- 仅针对当天运行 `python -m scripts.backfill_quote --asset USD_CNY`，GitHub Actions 可用 Backfill one missing quote 手动触发。脚本只访问 USD/CNY，不重新采集新闻或美股。
- 保存独立补采文件到 data/supplements/YYYY/MM/YYYY-MM-DD/USD_CNY.json，包含上游行情观测时间、实际采集时间、对照原始快照时间和来源。
- 渲染 HTML 时叠加补采记录，卡片标明补采 UTC 时间，并写入历史 quotes.csv。原始 data/daily JSON 保持不变。
- 补采时间晚于早晨正式快照，不能冒充 08:15 的盘前价格；无法抓到可靠报价时应失败，而不是估算或造数。

## 同一市场行情源滞后与官方修正

对同一个市场的主要指数，比较 market_date；发现单项滞后时先查官方交易所或可靠原始来源。无法核验时标注“疑似滞后”，不补造数据。

已核验的旧快照数据可以使用 data/supplements/<year>/<month>/<report-date>/<asset-key>.json 的 source_correction 修正，需满足原记录已存在、修正后的 market_date 更晚且不超过 report_date、HTTPS source_url 与 quote.source_url 一致。修正只叠加在生成 HTML 的视图上，原始快照不动；必须记录真实采集时刻与来源。不要在补录时虚构原始观察时间戳。历史行情CSV当前仍保存原始采集结果，研究时须合并独立修正记录。

## 单次完成的 ChatGPT 总控任务（2026-11）

- 每天北京时间08:15由 ChatGPT “全球市场雷达仓库维护”执行主总控；GitHub 定时采集在08:05、08:15、08:35、09:05提供独立兜底，08:50另有 ChatGPT “GMR 晨报补救验收”进行二次修复。
- 先读取当日 `data/daily/` 和最近 GitHub Actions：若当天无快照且无正在运行的采集任务，就创建 `data/requests/YYYY/MM/YYYY-MM-DD.json`，以 GitHub push 启动采集；若已在运行，优先检查日志。任务重试须有上限，避免无休止地重复 push。
- GitHub 的采集阶段只写原始数据，不再发布缺少AI分析的当日 HTML。必须得到 `data/analysis/` 中符合数据字典的完整分析 JSON，push 才会进行 `--render-only`。
- `python -m scripts.release_check --date YYYY-MM-DD` 用于校验本地发布产物包含01–06全章节、当日分析、核心行情与新闻引用；这个脚本不检测线上 GitHub Pages。
- ChatGPT 总控任务应再检查 GitHub Actions 成功提交、Pages deployment 成功，并尽可能验证公开页面日期和摘要与仓库内容一致。所有这些环节完成才汇报 `COMPLETE`；否则给 `DEGRADED` 或 `FAILED` 和对应链接。
- 自动任务不能保证无限期等待。执行期间可依次重试、有界恢复；遇到 GitHub权限限制、源数据不可用或超过执行窗口时必须明确汇报失败，保留当次诊断记录，不得说“已完成”。
- 如未来自部署 V2 Agent Harness，可以承接上述同一契约，将AI分析和重试放进持久化 worker，做到真正可恢复的工作流。

## 15:30 盘后复盘工作流

盘后复盘独立于实验 Agent。北京时间09:30前，晨报 Github workflow 在分析存在时运行 freeze-only，冻结预测方向、组合研判、板块映射、预选代表股到 data/forecasts；09:30后不可补冻或假装历史预测。下午工作日15:30/15:50，close.yml 执行采集和兜底，同样使用 market-radar-writer 并发组。

日常命令：

    python -m scripts.close_review --freeze-only
    python -m scripts.close_review --collect-only
    python -m scripts.close_review --render-only
    python -m scripts.close_review --check --date YYYY-MM-DD

代码中的 --date 绝非历史行情回填开关；collect-only/freeze-only 同时验证当前北京时间和日期。单日真实数据写入 data/close，分析数据写入 data/close_analysis；推送后自动渲染 reports/close。若自动采集失败，可推送 data/close_requests/YYYY/MM/YYYY-MM-DD.json 请求当天再采集。源站异常、无当日沪深300收盘K线时不冒充已结算，也不擅自宣布休市；保留原始错误。

盘后 GPT 总控需要检查晨报冻结、事实快照、新闻原始发布时间、来源引用、发布校验、GitHub Actions 及 Pages 实际上线状态；仅全部成功才报告 COMPLETE，否则明确 DEGRADED/FAILED。自动化无法无限期阻塞等待，运行时可作有限重试，最终必须反馈真实状态。

## 盘前冻结缺失的恢复规则

盘后任务**不得因为缺少 data/forecasts 而停止或只报 FAILED**。正常采集观察数据及 GPT 分析；有晨报时对照晨报板块（不算命中率），晨报缺失时采用固定观察池。若基准沪深300暂时缺数据，也继续抓取其他同日板块与股票并诚实标注不可计算超额收益。只有没有任何可靠同日行情时才不能形成有效收盘行情快照。报告质量/发布失败与预测准确率不可评分是两个不同状态。


## 2026-11-05 起：晨报自动化四道保障与完整验收

**每日北京时间执行顺序（不需要用户消息触发）**：

- 08:05：GitHub Actions daily.yml 主动拉取快照，提前避开08:15总控/采集同一时刻起跑的问题。
- 08:15：ChatGPT「全球市场雷达仓库维护」总控检查今日快照、主动补触发、核验新闻并向 data/analysis 写入完整分析；GitHub Actions 在 08:15 再次进行幂等兜底。
- 08:30：ChatGPT「每日全球市场与A股晨报」单独推送聊天消息；它不是仓库发布的成功凭据，尽可能与 data/daily 同口径。
- 08:35：GitHub Actions 第三次幂等补采或重渲染。分析文件推送会自动触发同一 workflow。
- 08:50：ChatGPT「GMR 晨报补救验收」独立检查日快照、分析、HTML、Pages 与 forecast，不依赖08:15主控会保持运行；缺失时有限次数主动补采、研究分析及重新触发 GitHub 渲染。
- 09:05：GitHub Actions 最后一次盘前冻结/HTML 兜底。分析若在09:30前就绪，则 daily.yml 先运行 freeze-only，再验证完整HTML；超过开盘不能伪装为盘前冻结。

**新增可重复的机器验收**：
    
    python -m scripts.morning_audit --date YYYY-MM-DD --require-published

该命令不访问外网，只对 GitHub checkout 的 data/daily、data/analysis、reports/index 和 data/forecasts 做本地交叉检查；报告层状态和冻结评分能力单独输出，news_digest、六章、六核心指标通过 release_check 联合验证。注意它不验证 Pages HTTPS/部署版本，必须由ChatGPT总控继续核对。出现 PENDING/FAILED/DEGRADED 或数据新鲜度问题需如实记录并尽最大能力恢复，不能把脚本退出码0就当作线上完整发布。

**边界**：四次 GitHub cron 并不代表 GitHub 承诺按分钟触发，ChatGPT任务也不会在任务返回之后无限轮询。08:50 是独立补救任务，能够避免仅靠用户提醒，但外部行情中断、GitHub限流或插件授权异常依然可能导致失败，届时必须反馈错误和当前状态。


## 核心指标的自动单项补采（2026-11-05）

原始日快照是不可变记录，早上08:05采集失败的个别核心报价**不会被直接重新写入 data/daily**。daily.yml 的08:05、08:15、08:35及09:05幂等触发现在都会在存在原始快照后运行：

    python -m scripts.backfill_missing --date YYYY-MM-DD

该脚本仅检查 USD_CNY、AUD_CNY、NASDAQ、SP500、DOW、AUD_USD 六大核心资产中原始 status=unavailable 或缺失的记录；如对应 data/supplements/YYYY/MM/YYYY-MM-DD/<asset>.json 已存在则跳过。重试成功的价格写入独立补采文件，记录真实补采时间，原始快照与缺失错误保留；未成功则记入日志，**不能补零、虚构行情或悄悄覆盖原始JSON**。

渲染层用 pipeline.with_supplements 叠加有效补采，scripts.morning_audit 也按同样视图验收，避免错误地把已补好的指标判为缺失。补采源可能滞后，仍需核实实际 market_date 与 observed_at_utc，不能将稍晚取得的报价冒充08:05原始采集价。

`scripts.backfill_quote` 的手动补采模式已增加正式分析门禁：即使补到报价，**没有具备market_summary、a_share_outlook、非空news_digest.items及有效来源引用的完整分析JSON时，也不会单独渲染HTML**。自动批量补采强制使用 render=False，由daily.yml在完整分析准备好后统一渲染并执行release_check/morning_audit。短暂来源异常不会导致一次早采失败永久固化到页面，但任何上游持续异常仍须按DEGRADED/FAILED报告。

## 国内指数上游行情滞后排查（2026-11-05）

- 已确认 Yahoo Finance 的 `000001.SS` 在11月5日08:18仍返回11月3日上证综指3608.10，尽管同一快照沪深300已更新11月4日。这是**源数据过期而不是GitHub触发失败**。11月4日真实上证收盘3686.17（+2.16%），详见[data/supplements/2026/11/2026-11-05/SSE.json](../data/supplements/2026/11/2026-11-05/SSE.json)。
- `scripts/sources.py` 对上证及沪深300尝试东方财富日K线接口作为优先行情源（`1.000001` / `1.000300`），只取中国市场已结束的交易日，不使用当天未收盘日K线；失败自动回退 Yahoo。该公开接口**并非交易所官方 API**，可能被限流和返回缺失，需运行日志/快照验证。
- 同一市场两项指数若市场日期不一致，会在采集数据中把较旧一项标记为 `stale` 而非 `ok`，附带异常原因。原始快照永不重写；有可核验的历史修正另存补录文件。11月5日上证修正来源为同花顺收盘快讯（并由英为财情历史行情交叉核对），**不是交易所官方直连**。
- CI 测试覆盖东方财富数据解析、未完结日线剔除、代码校验和 Yahoo 异常回退。明天必须验收实时接口成功返回（CI不能验证远端接口未来可用性）。

## 订正层研究数据验收

运行 `python -m scripts.curate_data` 可重建每日报价及全历史订正 CSV，且重复运行输出字节稳定；源修正变化通过 SHA256 与 Git 历史留痕。每天的 `daily.yml` 在单资产补采之后执行，原始文件不重写。检查 `data/curated/manifest.json` 的 `daily_files`、`quote_rows`、`source_corrected_rows`、`return_usable_rows`，不要仅以行数判断数据可信。模型训练优先筛选 quality_flags、`usable_for_return_analysis` 及 `available_at_utc`，避免盘中价当日终价。
