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

- 每天北京时间08:15由已有 ChatGPT “全球市场雷达仓库维护”任务启动一次总控检查；GitHub 定时采集 08:15、08:35 保留兜底，避免单点故障。
- 先读取当日 `data/daily/` 和最近 GitHub Actions：若当天无快照且无正在运行的采集任务，就创建 `data/requests/YYYY/MM/YYYY-MM-DD.json`，以 GitHub push 启动采集；若已在运行，优先检查日志。任务重试须有上限，避免无休止地重复 push。
- GitHub 的采集阶段只写原始数据，不再发布缺少AI分析的当日 HTML。必须得到 `data/analysis/` 中符合数据字典的完整分析 JSON，push 才会进行 `--render-only`。
- `python -m scripts.release_check --date YYYY-MM-DD` 用于校验本地发布产物包含01–06全章节、当日分析、核心行情与新闻引用；这个脚本不检测线上 GitHub Pages。
- ChatGPT 总控任务应再检查 GitHub Actions 成功提交、Pages deployment 成功，并尽可能验证公开页面日期和摘要与仓库内容一致。所有这些环节完成才汇报 `COMPLETE`；否则给 `DEGRADED` 或 `FAILED` 和对应链接。
- 自动任务不能保证无限期等待。执行期间可依次重试、有界恢复；遇到 GitHub权限限制、源数据不可用或超过执行窗口时必须明确汇报失败，保留当次诊断记录，不得说“已完成”。
- 如未来自部署 V2 Agent Harness，可以承接上述同一契约，将AI分析和重试放进持久化 worker，做到真正可恢复的工作流。
