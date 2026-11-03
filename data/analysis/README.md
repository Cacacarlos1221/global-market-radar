# Analysis payloads

由定时研究任务或人工核验后写入，路径为 `YYYY/MM/YYYY-MM-DD.json`。字段定义见 [数据字典](../../docs/DATA_DICTIONARY.md)。

不要在没有来源时自行编造消息因果、行情和A股预测。仅写入事实核验过的分析，并使用真实 evidence_urls。新文件推送后，GitHub Actions 会对存量快照重新渲染 HTML。
