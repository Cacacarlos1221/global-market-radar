# 手动/总控调度请求

当北京时间 08:15 的 ChatGPT 总控任务未发现本日行情快照且 GitHub Actions 没有正在运行的采集任务，可以通过 GitHub Connector **新建** `data/requests/YYYY/MM/YYYY-MM-DD.json` 来触发 `.github/workflows/daily.yml` 的 push 工作流。

请求体可以包含：

```json
{
  "report_date": "YYYY-MM-DD",
  "requested_at_utc": "实际UTC时间",
  "requested_by": "chatgpt_scheduled_orchestrator",
  "reason": "No daily snapshot or active collection run"
}
```

这个文件不包含价格、分析结果或凭据，仅作为可审计的触发信号。同日已存在请求时，不得重复创建：应检查运行记录和错误，再根据证据更新请求或使用已有工作流的重试操作。GitHub 08:15 和 08:35 schedule 继续作为兜底。

**注意**：工作流收集的是请求执行当刻的行情，不是历史08:15报价。原始快照一旦形成不可改写。
