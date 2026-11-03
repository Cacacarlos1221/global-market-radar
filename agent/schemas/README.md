# Analysis contract (v0)

结构严格沿用 `docs/DATA_DICTIONARY.md` 中的 `data/analysis` JSON（包含 `news_digest` / `news_sources`）。动态 source_ids 引用一致性和来源白名单在 `agent/validators.py` 中校验，并调用现有 `scripts.render.validate_analysis`。

`agent_meta` 额外记录 `harness_version`、`snapshot_sha256`、`snapshot_collected_at_utc`、`run_at_utc`、`run_mode` 与 `evidence_mode`，网页渲染器会忽略这些审计字段。

这是实验契约，不应让模型直接创建可信来源目录、决定 SHA 或覆写原始快照。
