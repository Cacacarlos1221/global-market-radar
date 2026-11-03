# Global Market Radar / Research Agent Flow v0.3（独立实验）

**Git branch:** experiment/market-analysis-agent-v0（基于 2026-11-03 最新 main 原型更新）。这个目录承载可执行的 Stage-2 Agent 编排，不是定时生产任务。现有事实采集、正式日报与 Pages 继续由 main 管理。

报告产品规范以 [docs/REPORT_SPEC.md](../docs/REPORT_SPEC.md) 为准：01 美元/人民币优先的核心行情、02 全资产行情、03 市场走势及可能驱动、04 核验新闻综述、05 A 股条件性盘前推演、06 来源引用和原始 RSS 折叠，最后是数据质量简述。**LLM 不直接改 HTML，不得覆盖原始事实快照。**

## 1. 可执行 Agent 图

    main scripts.pipeline → data/daily (append-only)
                  │
    [0 / Preflight] 原始快照哈希 + 补采数据 as-of 截点合并
                  │
    [1 / Research] 过滤未来 RSS + 规范化去重 → 人工事实核验队列
                  │                                  │
                  │                 news_sources reviewed evidence JSON
                  │                 （实际阅读来源后填 fact_notes）
                  └─────────────────────────┬────────┘
                                            │
    [2 / Analyst] 可替换 OpenAI-compatible LLM
                 → 03 market_summary
                 → 04 news_digest / news_sources
                 → 05 a_share_outlook / sectors / risks
                                            │
    [3 / Deterministic QA] JSON字段、source_ids、来源白名单、
                快照SHA、证据时间、补采时间、盘前/盘后标记
                                            │
    [4 / Critic] 第二次 LLM 作为审稿员查数值、证据、归因和时间逻辑
                ├── reject → blocked audit，不生成可发布稿
                └── approve → 再次通过确定性校验
                                            │
    [5 / Preview] agent/output/ 本地 JSON、HTML、research_queue、audit
                                            │
    [6 / Human Gate] 人工审核后单独 publish（禁止已有分析覆盖）
                                            │
    data/analysis/YYYY/MM/YYYY-MM-DD.json（只在本地）
                                            │
    [7 / Renderer] scripts.pipeline --render-only
                 → HTML（GitHub Pages 实际发布仍仅 main）

**这是一条有固定节点的 Agent Workflow（harness），不是自由规划、自带浏览器或能自主核实新闻的全自动新闻 Agent。** 其运行入口是 agent/main.py 的 flow；Python 负责工具和规则，LLM 负责推理与二次审查。没有新闻核验材料时 04 必须为空，不能把 RSS 标题视为证据。

## 2. 文件定位

- agent/flow.py：串行执行 / 审计 / 离线 HTML 预览 / 错误隔离。
- agent/orchestrator.py：行情及补采数据拼装、分析 Prompt、人工发布门禁。
- agent/research.py：新闻候选去重、去未来时间、未核验列表。
- agent/web_research.py + agent/research_runner.py：GDELT 网络检索与原始文章抓取（候选证据）。
- agent/research_agent.py：在模型 Key 可用时，基于不同来源的逐字引用进行候选观点交叉核对，不宣称事实已核验。
- agent/live_research.py + agent/official_runner.py：无需 Key 的央行/统计部门 RSS 与原始文章检索（待人工核实）。
- agent/tools/io.py：只读快照、SHA-256、严格 UTC 来源核验时间、补采 as-of。
- agent/model_client.py：兼容 Chat Completions 的模型 API（无需第三方依赖）。
- agent/critic.py / prompts/critic.md：第二轮 LLM 审核。
- agent/validators.py：字段和引用完整性验证，复用 scripts.render.validate_analysis。
- agent/output/：预览稿、证据队列和审计日志，gitignore，不会自动进入正式网页。
- tests/test_agent_flow.py、tests/test_agent_framework.py、tests/test_agent_research.py：无外网端到端模拟。

## 3. 最小可运行示例

从仓库根目录执行（Python 3.11+）。**不需要任何模型 Key 就能离线跑通第一阶段**：

    python -m unittest discover -s tests -v
    python -m agent.main plan --date 2026-11-03
    python -m agent.main flow --date 2026-11-03 --offline

此时产生：

    agent/output/2026-11-03/research_queue.json
    agent/output/2026-11-03/report.preview.html
    agent/output/2026-11-03/audit.json

该 HTML 是「行情 + 待分析提示」的安全预览，不是 AI 市场分析结果。CI 同样运行此命令，并上传可下载的 HTML / JSON Artifact。

**实际两轮模型流程**需要模型 API。设置以下三个环境变量（值仅在本地/仓库 Secret 中）：

    export MARKET_AGENT_BASE_URL="https://api.openai.com/v1"
    export MARKET_AGENT_MODEL="your-model-id"
    export MARKET_AGENT_API_KEY="your-secret"
    python -m agent.main flow --date YYYY-MM-DD --evidence /path/to/reviewed_sources.json

模型必须是兼容 OpenAI Chat Completions、并能严格输出纯 JSON 的模型。程序会发起两次模型请求（分析、审查），费用和时延取决于提供商。**未配置模型时不能声称已经完成真实 LLM 分析。**

审核证据示例参见 agent/examples/reviewed_sources.example.json。每条实际已阅读的来源须填写：

    {
      "id": "S1", "title": "确实阅读过的报道标题", "publisher": "发布机构",
      "url": "https://真实报道地址", "verification": "reported",
      "fact_notes": "实际核验的事实与发生时间（不可凭标题推断）",
      "published_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
      "reviewed_at_utc": "YYYY-MM-DDTHH:MM:SSZ"
    }

上面仅是字段说明，不能把示例作为真实证据文件。模型输出的来源 ID、网页引用 URL 都不具有信任权：只有审阅输入中存在的来源才会写入 final JSON。

**重跑规则**：每个日期的 agent/output 运行目录默认不覆盖。离线完成后，如需用同一日期正式模型跑，请先备份/检查并显式清理该日期 output 目录和旧预览 JSON，然后再次运行。这个操作只处理 gitignore 的实验产物，不要删除 data/daily。

## 4. 手动发布（仅在实验分支工作区执行）

通过第二轮 Critic 和结构化 QA 后，仔细查看：

    agent/output/YYYY-MM-DD.analysis.json
    agent/output/YYYY-MM-DD/report.preview.html
    agent/output/YYYY-MM-DD/audit.json

人工确认后，才可以运行：

    python -m agent.main publish --date YYYY-MM-DD --evidence /path/to/reviewed_sources.json --reviewed --render

必须是**同一次分析的原始预览哈希 + passed 审计记录**；任何手工篡改、改变源文件、迟到补采导致来源清单变化都会拒绝。目标 data/analysis 当天文件存在时也会拒绝覆盖。此命令仅修改当前本地 checkout，**不会自动 Git push、不会自动部署 Pages**。

2026-11-03 的 main 已存在正式分析 JSON，这一天请只做 plan / flow 预览，不要尝试覆盖发布。晚于 A 股开盘才运行的同日分析，会标记为 late_or_replay，不能用于无前视偏差的盘前命中率评估。

## 5. 自动化边界与待办

- **已实现并测试**：全量行情补采 as-of 筛选、RSS 去重与核验清单、模型适配、两轮 LLM 节点、可失败封闭的字段/引用检查、时点校验、预览 HTML、审计、人工批准发布、离线 GitHub Actions 演示。
- **尚未实现**：可作为事实依据的自主交叉核验、可靠的工具驱动新闻研究循环、模型 token/费用统计、自动重试与故障通知、质量基线与长期预测复盘，以及可信的 08:30 自动生产端到端任务。
- **非保证**：Critic 通过不等于所有财经事实都正确；人工审稿仍必需，不能用生成式模型的二次回答取代独立证据。
- **安全**：Agent 工作流只在实验分支启动；正式 data/analysis 的 push 触发和补采工作流按 main 分支受限；原始快照不可覆盖、实验输出不入库、API Key 不提交。若以后打算让 Agent 自动发布，必须先独立审计并得到明确授权。

先用离线 preview 检查现在的 HTML / 数据口径，再拿真实 API 做小批量双模型审查测试。模型与自动新闻研究框架成熟后，才考虑将 Stage-2 接管每日晨报，不要提前覆盖 main。


## 6. Windows 桌面「学习」目录部署与真实连接测试

需要 Windows 10/11、Python 3.11+、Git for Windows。请下载本分支的 agent/setup_windows.ps1 到 Windows 下载目录后执行：

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$HOME\Downloads\setup_windows.ps1"

脚本自动定位 Windows 桌面（包括 OneDrive 重定向），在桌面/学习/global-market-radar-agent 下克隆实验分支，创建独立 .venv，复制 agent/.env 模板，跑离线单元测试并预览 2026-11-03 快照。不会删除已有目录、修改主分支或覆盖 API Key。

模型配置仅在本机：

    [Windows Desktop 的实际目录]\学习\global-market-radar-agent\agent\.env

填写实际兼容 Chat Completions 的服务商参数，切勿上传此文件：

    MARKET_AGENT_BASE_URL=https://api.openai.com/v1
    MARKET_AGENT_MODEL=your-valid-model-name
    MARKET_AGENT_API_KEY=your-real-provider-key

OpenAI 的 API Key 在独立的 API 平台创建，ChatGPT Plus 订阅不包含 API 计费额度；其他兼容服务商需使用对应 URL、模型名与 Key。agent/.env 会自动读取。可以运行以下命令（PowerShell，先进入仓库根目录）：

    .\.venv\Scripts\python.exe -m agent.main doctor
    .\.venv\Scripts\python.exe -m agent.main smoke-model
    .\.venv\Scripts\python.exe -m agent.main research-official
    .\.venv\Scripts\python.exe -m agent.main research
    .\.venv\Scripts\python.exe -m agent.main flow --date 2026-11-03 --offline

- doctor：无成本检查 Python 和当前 Key 是否配置，永不打印密钥。
- smoke-model：向你选择的模型 API 发出一次真实最小 JSON 请求，确认 API Key、地址、模型和网络可用，会产生少量 token 消耗。
- research-official：无需 Key，读取官方来源 RSS 与网页，保存 agent/output/research/YYYY-MM-DD/official_sources.json 和 review_template.json。仅支持当前北京时间日期。
- research：无需 Key，调用 GDELT 新闻索引、尝试读取新闻网站原文，保存 agent/research_output/YYYY-MM-DD/publisher_candidates.json 与 audit.json。该模式依赖现有当日 data/daily 快照，不能用旧数据生成伪盘前事实。
- flow --offline：无需 Key，使用已存在原始快照生成安全行情 HTML 和未核验新闻候选。日期当天分析 JSON 已存在时绝不覆盖。

所有研究输入均为不可信候选。人工需逐条打开原文核验，把可用来源的 fact_notes 与 reviewed_at_utc 填完整、状态改为 reported 后另存为 reviewed_sources.json，删除不符合要求的条目；不要直接批量将模板从 needs_human_review 改成 reported。再用：

    .\.venv\Scripts\python.exe -m agent.main flow --date YYYY-MM-DD --evidence ".\agent\output\research\YYYY-MM-DD\reviewed_sources.json"

做两轮 LLM 生成与审查。注意每个日期的 agent/output/YYYY-MM-DD 只能生成一次，重跑前先备份清理实验输出目录，不要动 data/daily。2026-11-03 原仓库已经有正式分析，不能用此日验证发布覆盖。除 Key 之外，真实网络来源也可能返回 403/限流，错误会保留；真实机器上的完整结果应以本机日志为准。


## 7. macOS 桌面「学习」目录：本地环境和运行

适用于 Apple Silicon/Intel Mac，要求已安装 Git 与 Python 3.11+。**云端 Agent 无法代替你操作 Mac 的本地桌面；以下命令需要在 Mac 终端执行。**

复制执行以下命令。脚本会自动克隆当前实验分支到 \`~/Desktop/学习/global-market-radar-agent\`，创建隔离的 \`.venv\`，复制 \`agent/.env.example\` 到本地不受 Git 管理的 \`agent/.env\`，运行 40 项左右离线测试与 2026-11-03 快照 HTML 预览。不会在已有仓库上自动 git pull、reset 或覆盖本地密钥。

\`\`\`bash
curl -fsSL "https://raw.githubusercontent.com/Cacacarlos1221/global-market-radar/experiment/market-analysis-agent-v0/scripts/setup_agent_mac.sh" -o /tmp/setup_agent_mac.sh
bash /tmp/setup_agent_mac.sh
\`\`\`

如果要先检查脚本再执行，\`cat /tmp/setup_agent_mac.sh\`。安装后，进入项目：

\`\`\`bash
cd "$HOME/Desktop/学习/global-market-radar-agent"
.venv/bin/python -m agent.main doctor
.venv/bin/python -m agent.main research-official
.venv/bin/python -m agent.main research
\`\`\`

- \`research-official\`：免费官方 RSS + 官网原文，输出 \`agent/output/research/当日日期/\`，不需要模型 Key。
- \`research\`：GDELT 新闻索引 + 媒体正文，输出 \`agent/research_output/当日日期/web/\`，不需要模型 Key。
- \`research --research-model\`：在 GDELT 候选上额外运行一次 LLM 对照来源引文，**需要 Key 并产生模型费用**。结论仍标记待人工核验。
- 两种研究都是**当前北京时间日期**的联网快照，拒绝回填历史盘前时点，防止前视偏差。公开网站可能出现 403、限制或缺少可读正文；检查各自 \`audit.json\` 的错误记录。每种研究同一天不允许静默覆盖输出，重跑应人工归档旧结果。

### 仅在本机添加模型密钥

\`\`\`bash
nano "$HOME/Desktop/学习/global-market-radar-agent/agent/.env"
\`\`\`

\`\`\`dotenv
MARKET_AGENT_BASE_URL=https://api.openai.com/v1
MARKET_AGENT_MODEL=实际可调用的模型 ID
MARKET_AGENT_API_KEY=实际服务商的 API Key
\`\`\`

OpenAI 可到 https://platform.openai.com/api-keys 创建 API Key；其他 OpenAI Chat Completions 兼容服务商使用其对应的 URL、模型 ID 和 Key。**不要把 Key 粘贴到聊天、提交到 GitHub 或写进 README。** \`doctor\` 只报告是否配置，不会打印 Key。ChatGPT Plus 订阅与 API 额度分别计费。

配置好以后测试真实接口：

\`\`\`bash
cd "$HOME/Desktop/学习/global-market-radar-agent"
.venv/bin/python -m agent.main doctor
.venv/bin/python -m agent.main smoke-model
\`\`\`

两轮市场分析（Analyst + Critic）用 \`flow --date YYYY-MM-DD --evidence /绝对路径/reviewed_sources.json\`。**必须先打开真正来源并人工填好核验事实及时间**；research 生成的模板不能直接输入。运行产物在 \`agent/output/\` 内，只生成本地预览并保留审计；不部署到 main。2026-11-03 已有分析产物，不用它测试发布覆盖。

### 测试边界（2026-11-03）

GitHub Actions（Linux/Python 3.12）已通过全部单元测试、离线 HTML 预览和官方来源联网冒烟。官方来源抓到 1 条候选材料并记录 1 个请求错误。这证明了远端执行能力，**不等于已经在你的 Mac 上创建目录，也不等于真实模型 API 已经联通**。本机完整执行结果以终端显示为准。
