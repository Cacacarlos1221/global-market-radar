# GMR 盘后验证 · 研究和运维契约

## 目的与范围

北京时间每个 A 股交易日 15:30 启动收盘行情采集，随后由 ChatGPT 总控分析晨间盘前预测与真实走势的偏差、筛选盘中发生且可核验的重要事件，生成独立静态盘后报告。

此模块属于 main 分支的业务主线，与实验 Agent 框架分支无关。前瞻推断、已发生行情和后验解释必须保持独立记录，不允许用未来信息重写原预测。

## 项目入口

- 晨报首页：index.html
- 当日盘后最新页：reports/close/index.html
- 盘后历史：reports/close/archive.html
- 盘后每日页：reports/close/YYYY/MM/YYYY-MM-DD.html

## 定时编排

1. 08:05/08:15/08:35/09:05 GitHub Actions 分别负责提前采集、盘前重试与最后冻结/报告兜底；当 verified analysis 已存在且北京时间尚未到 09:30，执行 scripts.close_review --freeze-only，冻结报告日、原始预测、分析生成时间、分析文件 SHA256，以及当时的板块/代表股跟踪池。
2. 15:30（UTC 07:30）GitHub Actions close.yml 定时采集；15:50 同样执行幂等兜底。只有本地北京时间达到 15:30、日期等于报告日期且沪深300同日收盘 K 线有效时才保存原始事实。
3. ChatGPT 15:30 总控检查采集与冻结状态，必要时向 data/close_requests/YYYY/MM/YYYY-MM-DD.json 提交请求触发工作流；读取收盘原始 JSON 及真实新闻来源，对原始预测逐条核验，生成 data/close_analysis/YYYY/MM/YYYY-MM-DD.json。
4. 分析文件 push 自动 render-only、单日发布检查及 GitHub Pages 部署；报告 COMPLETE 必须核实网页真实可访问且为对应交易日。来源缺失、冻结缺失或可评分标的缺失只能标记 DEGRADED；采集/部署失败标记 FAILED。

GitHub scheduled 工作流存在排队和延误，不承诺准点完成或无限等待；ChatGPT 定时任务也不能充当常驻 worker。

## 行情接口与严格质量门禁

- 公开东方财富板块分类及同日 K 线接口为非官方接口，可能限流、返回空或改变字段。采集前先确认沪深300指数同一交易日，随后每个板块和每只股票都必须自身拥有匹配日期的日 K。
- 日涨跌幅按同一标的当日收盘价和上一可用交易日收盘价计算；指数、股票都带 market_date、reference_close、value_kind、source。没有同日数据返回 unavailable，不抄昨日收盘。
- 中国市场周末直接跳过；工作日没有行情时不能立即断言“休市”，因为也可能是 API 异常。节假日由总控结合交易所公告或权威日历判定。
- config/sector_watchlist.json 的固定跟踪池：名称匹配透明、股票仅为固定观测标的，绝非推荐。名称不完全一致的代理主题可以展示，但标记 is_proxy=true，不参与方向命中率。
- 热门板块使用当日现有板块榜与可核查同日K线，top5 板块及每板块不超过2只领涨活跃股；热股于盘后才选择，因此不参与预测命中率。
- 盘后新闻 RSS 只是检索线索，09:30–15:00 发表范围外的新闻不能称为盘中新增驱动。GPT 必须二次查阅可靠消息的正文或官方材料，保留引用、时间、核验状态。没有证据时不猜测因果。

## 预测评分原则

晨报 a_share_sectors[] 的每个条目对应 **一个预测样本**。若原始条目为“半导体、AI服务器与存储”，可以展示三个子板块，但仅在三者全部拥有当天有效且语义直接对应的指数时，采用三者等权涨跌幅，得到一条组合判断的实际表现。

- positive：等权日涨跌 > 0 时方向一致，< 0 时方向偏离；negative 相反。
- 不可评分：等权日涨跌恰好为0、任意子板块指数缺失、板块语义为代理、方向标签是 watch/mixed/neutral、缺晨间有效冻结。
- 超额收益：该条组合的等权日涨跌 - 沪深300日涨跌（百分点），与方向一致率分别展示。方向一致不等于跑赢市场。
- 代表股按已冻结标的池展示全部收盘结果，不事后只挑领涨股。单股业绩、概念差异不得直接替代板块判断。
- 不将未预测的市场强势板块倒算为预测成功。长期准确率需保存完整分母、来源及交易日，统计显著性和基线需独立研究。

## 盘后分析 JSON 合同

路径：data/close_analysis/YYYY/MM/YYYY-MM-DD.json

示意格式（不是事实分析）：

    {
      "report_date": "YYYY-MM-DD",
      "generated_at_utc": "ISO-8601 UTC",
      "summary": "今天大盘和盘前研判偏离的总结，需要有真实收盘数据作支持",
      "key_findings": [
        {"title": "核心发现", "finding": "描述收盘事实与条件推演的关系", "source_ids": []}
      ],
      "attributions": [
        {"sector": "半导体", "observation": "相对走势", "explanation": "可能的驱动与限制条件",
         "causal_status": "hypothesis", "source_ids": []}
      ],
      "new_events": [
        {"title": "经核验的盘中事件", "summary": "已确认事实",
         "published_at_utc": "ISO-8601 UTC", "source_ids": ["S1"]}
      ],
      "news_sources": [
        {"id": "S1", "title": "真实报道标题", "publisher": "机构",
         "published_at_utc": "ISO-8601 UTC",
         "url": "https://真实网页",
         "verification": "reported"}
      ],
      "next_watch": ["后续需要验证的变量"]
    }

不要复制示例的假链接。key_findings、attributions 若无新闻来源，应仅陈述已存 JSON 支撑的收盘事实或明确写为不确定性假说。new_events 每条必须引用实际有效的 news_sources.id，不能引述未核验 RSS 标题作证据。

## 复现与故障处理

从仓库根目录：

    python -m unittest discover -s tests -v
    python -m scripts.close_review --freeze-only
    python -m scripts.close_review --collect-only
    python -m scripts.close_review --render-only
    python -m scripts.close_review --check --date YYYY-MM-DD

原始 data/forecasts 和 data/close 快照一经提交不可静默覆盖；补数必须新建带时点/来源的显式修订，不得将下午才采到的事实伪装为盘前快照。需要重新抓取过去日期时，不得滥用 --date：采集与冻结命令会检查本地当天及时间窗口。

源站数据质量、成交状态与新闻真实性均存在不可控风险。本项目仅用于研究与信息整理，不构成投资建议。

## 无冻结时的盘后观察模式（2026-11-04 补充）

盘前冻结只约束**严格预测命中率**，不是盘后报告的生成前提。无冻结时也必须尽力生成完整盘后事实及研究总结，优先级：
1. 当日 data/analysis 中有当日 09:30 前生成的晨间判断：作为**未冻结的晨间观察主题**关联原有板块与预设代表股，不对方向进行计分。保留 morning_analysis_sha256、来源状态 morning_analysis_unfrozen，不冒充冻结。
2. 当日晨报无法核验或缺失：自动使用 config/sector_watchlist.json 的固定观察池（watchlist_only），同样采集板块指数、代表股、热股、沪深300及新闻，但不称之为盘前预测。
3. data/close 的同日价格可部分可用；即便沪深300接口故障，也不应跳过其他可靠同日板块和代表股。没有任何同日收盘事实时才不生成行情快照；缺失项目保留错误与降级说明。

无冻结时 direction_hit 必须全部为 null，页面显示“仅供观察、不适用准确率”，不阻止 GPT 总结和发布。COMPLETE/DEGRADED/FAILED 应由**收盘数据、分析及网页发布质量**决定，缺冻结只影响预测评分，不能单独让整份盘后报告失败或降级。无法核实的资讯不作因果判断，但不妨碍对真实收盘波动进行总结。

## GMR 研究称谓与子板块呈现规范（2026-11-04）

- 每日 HTML 的 03 节统一命名 **GMR 盘后复盘与新闻归因**；叙述使用“GMR 观察 / GMR 研判 / GMR 发现”，不要以“GPT”作为研究报告署名。ChatGPT 是后台总控执行工具，不是网页中的研究品牌。
- 晨报原始单条行业判断可能包含多个主题，例如“半导体、AI服务器与存储”：**原始预测仍然一条，方便审计与防重复计分；页面内子板块分别显示各自当日涨跌及相对沪深300的超额收益（百分点）**。
- 某个主题使用“液冷服务器”等代理板块时，要说明原主题、所用代理板块与差异；可以展示数值观察，但不把代理指数作为原主题的严格验证。
- 只有当全部子板块有严格可比的同日指数时才考虑展示组合等权涨跌；缺少完整指数时**不需要制造三板块合成指数，也不应影响单个板块与大盘的对比**。
- 对暂时缺少指数映射的出口制造、券商与宽基等主题，继续诚实显示无法比较；尚未确定新的合理映射或统一展示设计之前，不强制修改现有布局。


## 晨报与盘前冻结的容错接力（2026-11-05）

晨间 GitHub Actions 已增加 08:05/08:15/08:35/09:05 四个北京时间触发窗口；ChatGPT总控在08:15，08:50另有独立的补救验收任务。只要完整 data/analysis 在09:30前提交，daily.yml 的 analysis push 流程先冻结预测，再验证01–06完整HTML并发布。scripts/morning_audit.py 独立核对真正的 frozen_at_utc 与 analysis_sha256，避免今天（11月4日）出现的“有完整晨报却没有盘前冻结”再次被误认为完全合格。

如果某次调度/数据发布延迟导致超过09:30，不能补造冻结；但晨报和下午观察仍按各自发布质量要求执行。网页发布成功和预测评分资格是两个独立指标。


## 行情源502时的历史代码降级与修订契约（2026-11-05）

- `data/close/YYYY/MM/YYYY-MM-DD.json` 为不可变的原始盘后采集快照，可能带有板块列表接口HTTP 502/503等失败记录；**不可静默覆盖它**。
- GitHub `close.yml` 在15:30之后采集原始事实后运行 `python -m scripts.close_review --enrich-only --date YYYY-MM-DD`。如果原始快照中板块报价缺失，则只允许从**早于当日报告日**的、已核验 `data/close` 历史快照恢复供应商的**板块名称、类型与代码身份**。本日的涨跌和收盘价必须另外请求对应代码的**当日真实K线**；绝不复制过去日期的涨跌幅。
- 如成功恢复，写入 `data/close_revisions/YYYY/MM/YYYY-MM-DD.json`：含 `original_close_sha256`、`revision_kind`、`enriched_at_utc`、`recovered_board_names`；每条报价含 `identity_mapping_asof`、`recovered_at_utc`。原始收盘快照仍保持不变，作为审计证据。
- `render_close` 和 `check_release` 优先读取已存在的修订快照；否则读取原始快照。研究建模同样必须明确采用原始版还是已核验修订版及其采集时点，不能把修订后的价格伪装为原始冻结时刻已知。
- 只针对**早晨已固定跟踪池允许的板块别名**匹配历史供应商代码；AI服务器→液冷服务器、稀土→稀土永磁等代理继续明确标记 `is_proxy=true`，不能因为恢复报价就变成严格评分标的。
- 对主题如券商与宽基、贵金属、出口制造等，若没有预设且语义对应的合法映射则继续不计分；不事后挑板块提高命中率。若榜单接口失败，即使已恢复部分主题指数，也不能根据昨日热度生成今日热门Top5；维持列表缺失并提示。
- **文字结论必须跟随数据修订更新**：若板块原先缺失，后来已恢复指数，报告 summary、key_findings、attributions、下一步观察与评分描述均要同步更正。今日具体修订实例见 `data/close_revisions/2026/11/2026-11-05.json`。
