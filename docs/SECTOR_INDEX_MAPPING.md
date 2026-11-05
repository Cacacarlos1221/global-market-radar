# GMR 板块指数映射：发现 → 提醒 → 用户确认 → 未来冻结

> 生效日期：2026-11-05 起。**候选指数不等于用户批准，也不等于严格预测可评分。**

## 目标与产物

盘前研究可能连续提及「贵金属」「券商与宽基」「出口制造」等主题，但这些主题如果没有确定的、可重复取到同日收盘K线的股票行业指数，盘后就只能记为*方向已预测但未完成验证*。本机制不会静默将这些缺失转化为预测失败，也不会仅因有股票收益就把它当板块指数。

- `config/sector_index_registry.json`：待人工确认的候选及`approved`名单。当前贵金属候选为东方财富行业「贵金属」BK0732，官方身份页面 https://quote.eastmoney.com/bk/90.BK0732.html；尚需用户确认用于GMR的预测口径，以及正式日K/成分核验。
- `scripts/sector_mapping_audit.py`：对最近40份已提交的收盘快照（优先读取修订视图）检查缺轨、无指数定义、无确认代码、代理指数；仅已有代码但当日行情失败归为行情故障，不把它误当作用户需挑新指数的问题。
- `data/quality/sector_mapping/YYYY/MM/YYYY-MM-DD.json`：按日留存审计记录；`data/quality/sector_mapping_latest.json`：最新总表。字段包括真实观测日、次数、对应盘前标签、候选代码和确认问题。单一组合内的多个指数缺口合并为**一条用户决策请求**。
- `.github/workflows/sector_mapping_audit.yml`：北京时间交易日15:55先扫描以便16:05消息读取，16:25再扫描以纳入晚到修订并提交台账；同时提供手工触发和候选配置变更触发。
- ChatGPT 原有的**16:05「GMR 盘后补救验收」**任务：在完成原有盘后数据/研究/HTML补救后主动向用户推送最多3个最重要的待确认指数问题；即使16:25独立扫描尚未执行，也读取今天的冻结/收盘数据并结合待确认台账提出问题。平台当前定时任务名额已满，因此不新建第六个定时任务。

## 状态分类

| 类型 | 应如何处理 |
|---|---|
| 已给出positive/negative、但指数未定义 | 高优先级，向用户询问精确指数名称、代码与计分口径 |
| 主题实际只能用相关概念指数代理 | 明示代理，用于走势观察；未经用户提前确定严格测量目标，不计方向命中率 |
| 已确定代码但当天行情API失败/交易暂停 | 是采集/数据质量故障，不要求用户重新选择指数 |
| mixed/watch/neutral | 仍跟踪并可迭代映射，但不能事后擅自转换成明确看多/看空 |
| 已批准、且批准日之后的生效日期已到 | 未来晨报的固定跟踪池读取批准定义，并把批准记录与注册表SHA写入不可变冻结快照 |

## 采纳一个新指数的完整手续

1. **GMR提出候选**：供应商、名称、代码、属于股票行业还是商品价格指数、候选的来源、能否获得日K及成分股信息、与盘前主题的语义是否对应。没有经过源站确认时明确记`pending`。
2. **用户明确确认**：例如“以后把贵金属固定为东方财富贵金属 BK0732”。用户也可以否决并指定另一条指数，或要求把组合拆成子板块。
3. **核实后录入**：将用户认可的`track`写入`config/sector_index_registry.json`的`approved`，其中必须含`status="approved"`、`topic`、真实`approved_at_utc`、**晚于批准自然日**的`effective_from`、`track.key/name/terms/board_names/board_type`，优先带已经核验的`track.board_code`、`track.board_name`与可选的事先选定代表股`stocks`。
4. **只在未来冻结应用**：`freeze_forecast`根据批准时间和生效日把track并入冻结的`watchlist`，保存`sector_mapping_approvals_applied`、`sector_mapping_registry_sha256`。若批准了BK代码，盘后可直接请求同日`90.BKxxxx`日K，不完全依赖容易报502的板块榜单。
5. **独立验收**：对应日期的板块身份、真实日K、方向标签、是否代理和评分必须逐项核对；既有日快照`data/forecasts`、`data/close`不可追溯改写。若报价缺失，依旧不评分。

```json
{
  "topic": "贵金属",
  "status": "approved",
  "approved_at_utc": "<用户实际确认时的UTC时间>",
  "effective_from": "<晚于批准日的未来交易日>",
  "track": {
    "key": "precious_metals",
    "name": "贵金属",
    "terms": ["贵金属"],
    "board_type": "industry",
    "board_names": ["贵金属"],
    "board_name": "贵金属",
    "board_code": "BK0732",
    "stocks": []
  }
}
```

*上例仅供后续批准时填写；**当前approved仍为空**，不可当作已批准状态。*

## 当前已发现的问题（2026-11-05）

仓库可证实的两日缺口包括「券商与宽基指数」「出口制造」、及代理主题「AI服务器」「稀土」；「贵金属」在可核查的11月5日盘前冻结中出现一次（用户另反馈已连续关注两日，但不修改历史计数）。贵金属、券商与宽基是优先需要确认的两条；同日用户确认后也**不得改写11月5日已经冻结的预测及评分分母**。

查询当前台账：

```bash
python -m scripts.sector_mapping_audit --date YYYY-MM-DD
python -m unittest tests.test_sector_mapping_audit -v
```
