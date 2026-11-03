# Market Analysis Agent · 独立实验（v0.1）

> 分支：`experiment/market-analysis-agent-v0`。本目录是 2026-11-03 讨论的固定 harness agent **概念验证框架**，不是已部署的无人值守晨报。**main 的自动采集、HTML、定时任务均不修改，也不新增定时触发。**

## 我们讨论的目标流水线

```text
Stage 1 [现有 main] scripts/sources.py + scripts/pipeline.py
        │  行情/RSS采集、保留原始快照、quotes.csv/events.csv
        ▼
  data/daily/YYYY/MM/YYYY-MM-DD.json (immutable)
        │
Stage 2 [本实验 agent] 读取快照 + 收集候选新闻
        ├─ 新闻核验与去重（目前人工审核清单；自动核验待实现）
        ├─ 主 Agent + 可替换 LLM API（OpenAI-compatible chat completions）
        ├─ 03 行情归因 / 04 重要新闻综述 / 05 A股条件性研判
        ├─ schema + 来源ID + 价格时间 + 快照SHA校验
        └─ agent/output/YYYY-MM-DD.analysis.json（预览，不入库）
        │  人工审阅；显式 --reviewed 发布；不覆盖既有分析
        ▼
  data/analysis/YYYY/MM/YYYY-MM-DD.json
        │
Stage 3 [复用 main] python -m scripts.pipeline --render-only
        ├─ index.html / reports/YYYY/MM/YYYY-MM-DD.html / archive.html
        └─ 审核后单独 git commit + push；GitHub Pages 只展示 main
```

**04 / 国际重要新闻综述** 是经过核验的 3–5 条重要事件及市场影响（少于3条也可以，最多6条）。**06 / 新闻来源与参考资料** 由 `news_sources` + 原始 RSS 折叠列表组成；新闻来源不能被误当成结论。数据质量保留在页脚和 JSON。原定的“07”未引入新章节，延续 main 已实施的 04/06 结构。

## 目录

- `main.py`：手动运行入口，plan / generate / publish 三步分离。
- `orchestrator.py`：分层流程、预览与发布、非盘前回放标记。
- `model_client.py`：不依赖第三方包的 OpenAI-compatible API 适配器。
- `tools/io.py`：快照读取、来源白名单与人工证据输入。
- `prompts/system.md`：固定约束和输出格式。
- `validators.py`、`schemas/`：本地验证与可追溯契约。
- `examples/reviewed_sources.example.json`：核验来源文件格式。
- `output/`：本地预览，已忽略，不应自动提交到公开仓库。

## 如何尝试（Python 3.11+）

在仓库根目录运行；必须已有对应报告日的 `data/daily` 快照。

```bash
python -m agent.main plan --date 2026-11-03
# 有独立人工核验材料后：复制 agent/examples/reviewed_sources.example.json，填写日期和 news_sources
# 每条已核验新闻需 id/title/publisher/url/verification=reported/fact_notes/reviewed_at_utc
# 可选 published_at_utc，UTC 时间必须是 ISO-8601；记录真实阅读核验时间
export MARKET_AGENT_BASE_URL="https://api.openai.com/v1"
export MARKET_AGENT_MODEL="your-model-id"
export MARKET_AGENT_API_KEY="your-secret-key"
python -m agent.main generate --date 2026-11-03 --evidence path/to/reviewed_sources.json
# 审核预览后，仅在目标 analysis 尚不存在时允许显式发布
python -m agent.main publish --date 2026-11-03 --evidence path/to/reviewed_sources.json --reviewed --render
python -m unittest discover -s tests -v
```

**注意：**仓库 main 已有 2026-11-03 的正式 `data/analysis`，所以当天不能用 publish 覆写。可仅运行 plan；试生成请在合适新日期的已冻结快照上进行。未提供人工核验来源时，新闻综述必须为空，不能把 RSS 标题升级为已核实新闻。模型 API 本身**不能**自动联网核验新闻。

## 当前边界与下一步

1. 已搭建：输入快照、人工证据清单、模型可替换适配器、模型草稿、来源白名单、静态结构校验、独立预览、人工批准发布接口。
2. 待实现：新闻全文检索/二次来源核验、事件去重、事实与推断逐句证据校验、行情异源交叉核对、重试/成本限额、日志与失败告警、沙箱回放评测、CI 与可恢复运行。
3. 待成熟后：以固定时间触发 Stage 1 → Stage 2 → Stage 3；先平行运行数日并比较质量，再考虑替换人工分析任务；不能直接让测试分支发布到正式 Pages。
4. 凭据只放本地环境变量或 GitHub Actions Secrets，绝不提交 Key、用户资料、付费新闻原文。正式自动发布前还需实现可审计的新闻核验闭环与更严格的故障隔离。

这套框架采用**一个主 Agent + 常规 Python 工具**，不预设复杂多 Agent，避免把联网采集、内容真伪、数值计算都交给 LLM。其范围刻意小，方便后续分步讨论与迭代。
