# 2026-11-10 GMR A股盘后事前检查

**预检时间**：北京时间2026-11-10早盘，今日交易收盘尚未发生。本页只记录已核实的上午链路与防故障实验，不提前宣布今天下午的收盘复盘成功。

## 历史根因（2026-11-09）

- ChatGPT盘后总控原定15:30，实际15:38:50唤醒，15:39:38结束；GitHub收盘事实约15:40才落库，因此总控在真正收到当日行情前就返回。
- 旧16:05独立补救任务在11月9日北京时间16:39核查时，最近一次运行仍是11月8日。不能声称当日救援已经执行。
- GitHub部分 `schedule` 记录直到北京时间11月10日凌晨01:44左右才运行；这意味着依赖 cron 的收盘采集可能晚于下一交易日开始，不可承诺准点。
- 原 `close.yml` 只确定性采集和渲染；没有GMR研究JSON时不生成当日HTML。**行情成功、研究未完成**是反复发生的单点依赖。11月9日最终由人工独立核对真实新闻后生成分析JSON才恢复上线。

## 今日事前已完成的动作

- **2026-11-10盘前预测已冻结**：北京时间08:20:12，对应 `data/forecasts/2026/11/2026-11-10.json`，在09:30之前。
- GitHub目前提供15:30、15:50、16:12三次行情采集机会；ChatGPT 15:55总控与16:25独立救援任务已检查均为 `enabled=true`。自动化工具的调度是否准点仍需在下午核验。
- 新增 `scripts/close_facts_fallback.py` 与 `data/close_fact_analysis/`：无独立研究时从**当天真正有效K线**生成**事实版**JSON/HTML，包含所有原始盘前研判与有效同日板块行情、按冻结规则机械计算的评分资格；`news_sources=[]`且`new_events=[]`，不拿RSS标题冒充已核验新闻。
- `scripts/close_review.render_close` 先读正式研究`data/close_analysis`，否则读事实版，两者文件隔离。事实版页面明显标记 **DEGRADED / 待独立新闻研究**，`--check` 返回 `has_independent_research=false`。即使研究JSON出现格式/日期错误，也能保留事实版而不谎称COMPLETE。
- 两条ChatGPT任务的保存prompt均已加入：即使今天事实版页面已上线，只要缺正式`data/close_analysis`，仍要开展独立新闻核验和完整报告；不能把事实版当完成。
- GitHub workflow还响应人工/其他agent提交的原始`data/close/`、`data/close_revisions/`和独立研究JSON，自动更新网页。GitHub自己用GITHUB_TOKEN提交文件不触发递归workflow，避免无限循环。

## 已真实执行的隔离演练

GitHub Action [GMR after-close morning preflight #42733553251](https://github.com/Cacacarlos1221/global-market-radar/actions/runs/42733553251) 使用2026-11-09的**真实封存收盘快照**复制到临时目录：

| 模拟故障 | 期望 | 实际 |
|---|---|---|
| 没有独立GMR研究JSON | 发布事实HTML，标记DEGRADED | 通过 |
| 独立GMR研究JSON补齐 | 优先显示研究版，原事实文件保留 | 通过 |
| 独立研究文件错误 | 自动退回事实版DEGRADED而不假冒研究 | 通过 |
| 历史原始行情不可变 | 临时复制验证，不能修改仓库原始文件 | 通过 |
| 当日晨间冻结 | 2026-11-10 09:30前 | 通过 |

最终`preflight_ok=true`；没有将11月9日重新发布或篡改历史预测。

## 下午真正的验收门槛

只有以下结果才算**完整研究成功**：`data/close/YYYY/MM/YYYY-MM-DD.json`含当天有效行情，`data/close_analysis/YYYY/MM/YYYY-MM-DD.json`含独立核验的GMR研究，`reports/close/YYYY/MM/YYYY-MM-DD.html`与盘后首页对应同一天，并确认Actions和Pages发布。当只存在`data/close_fact_analysis`时应报告`DEGRADED`：用户至少能看见当天行情，但**完整研究仍需16:25独立救援继续处理**。

风险：GitHub和ChatGPT调度由不同平台管理；代码可以预防“有行情、没研究就整页空白”，但不能保证外部schedule百分之百在指定分钟启动。若两个自动任务和GitHub采集都没有触发，上午的预检本身不能代替下午的实时触发。
