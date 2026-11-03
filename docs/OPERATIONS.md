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
