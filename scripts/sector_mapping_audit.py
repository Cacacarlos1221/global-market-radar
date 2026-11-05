"""Audit repeatable market-sector mappings; never auto-approve a proposed index."""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .close_review import ROOT, data_path, effective_close, load_json
BJ = ZoneInfo("Asia/Shanghai")
LABELS = {
    "no_track": "晨报主题没有固定跟踪指数",
    "undefined_index": "跟踪子板块尚无标准化指数定义",
    "undefined_benchmark": "组合内宽基指数尚未明确口径",
    "identity_missing": "有候选板块名称，但没有核验通过的指数代码",
    "proxy_requires_definition": "现有板块是代理指标，需确认是否适合该预测主题",
}
PRIORITY = {"high": 0, "medium": 1, "low": 2}
def issues_for(group):
    components = group.get("components") or []
    if not components:
        return [(group.get("sector", "未命名主题"), "no_track")]
    result = []
    for part in components:
        topic = part.get("name") or group.get("sector", "未命名主题")
        kind = part.get("board_type")
        if kind == "benchmark" and not part.get("board_code"):
            result.append((topic, "undefined_benchmark"))
        elif kind == "none":
            result.append((topic, "undefined_index"))
        elif part.get("is_proxy"):
            result.append((topic, "proxy_requires_definition"))
        elif not part.get("board_code"):
            # Quote failures for a known code belong to data QA, not mapping approval.
            result.append((topic, "identity_missing"))
    return result
def audit(asof, root=ROOT):
    datetime.strptime(asof, "%Y-%m-%d")
    path = root / "config/sector_index_registry.json"
    registry = load_json(path) if path.is_file() else {"approved": [], "proposals": []}
    approved = {x.get("topic") for x in registry.get("approved", [])
                if x.get("effective_from", "9999-99-99") <= asof}
    proposals = {x["topic"]: x for x in registry.get("proposals", [])
                 if x.get("status", "").startswith("pending")}
    files = sorted(x for x in (root / "data/close").glob("*/*/*.json")
                   if x.stem <= asof)[-40:]
    recorded = defaultdict(lambda: {"dates": set(), "groups": set(), "biases": set(), "reasons": set()})
    for file in files:
        day = file.stem
        try:
            snap = effective_close(root, day)
        except (OSError, ValueError, KeyError):
            continue
        for group in snap.get("predicted_groups", []):
            label = group.get("sector", "")
            for topic, reason in set(issues_for(group)):
                # Composite decisions are reviewed once, not as three noisy notices.
                review_topic = label if label in proposals else topic
                key = (review_topic, reason)
                recorded[key]["dates"].add(day)
                recorded[key]["groups"].add(label or topic)
                recorded[key]["biases"].add(group.get("bias", "unknown"))
                recorded[key]["reasons"].add(LABELS[reason])
    current_file = data_path(root, "close", asof)
    latest_data_available = current_file.is_file()
    issues = []
    topics = set(proposals) | {key[0] for key in recorded}
    for topic in sorted(topics):
        if topic in approved:
            continue
        proposal = proposals.get(topic, {})
        topic_records = [(kind, val) for (name, kind), val in recorded.items() if name == topic]
        dates = sorted(set().union(*(x["dates"] for _, x in topic_records))) if topic_records else []
        reasons = sorted(set().union(*(x["reasons"] for _, x in topic_records))) if topic_records else []
        biases = sorted(set().union(*(x["biases"] for _, x in topic_records))) if topic_records else []
        group_names = sorted(set().union(*(x["groups"] for _, x in topic_records))) if topic_records else []
        if not dates and not proposal:
            continue
        priority = proposal.get("priority") or ("high" if "positive" in biases or "negative" in biases or len(dates) >= 2 else "medium")
        candidates = proposal.get("candidates", [])
        issues.append({
            "topic": topic, "priority": priority, "status": proposal.get("status", "needs_mapping_review"),
            "observed_dates": dates, "observed_days": len(dates), "last_observed": dates[-1] if dates else None,
            "seen_today": asof in dates, "groups": group_names, "biases": biases,
            "gap_reasons": reasons, "candidate_indices": candidates,
            "user_question": proposal.get("question") or ("请确认「" + topic + "」的固定指数代码、供应商与是否仅作代理观察。"),
            "user_reported_recurrent": bool(proposal.get("user_reported_recurrent")),
            "existing_proposal": bool(proposal),
        })
    issues.sort(key=lambda x: (PRIORITY.get(x["priority"], 9), -int(x["seen_today"]),
                               -x["observed_days"], x["topic"]))
    return {
        "schema_version": "1.0", "audit_date": asof,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_close_snapshot_present": latest_data_available,
        "verified_close_days_scanned": [f.stem for f in files],
        "pending_count": len(issues),
        "high_priority_count": sum(x["priority"] == "high" for x in issues),
        "pending": issues,
        "notes": [
            "用户反馈的连续出现次数与仓库可验证的observed_days分开记账",
            "候选指数和代理都不能自动进入严格预测评分，必须用户确认并在未来盘前冻结",
            "已有代码但同日行情接口失败应由数据QA处理，不应自动归类为指数定义缺口",
        ],
    }
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Asia/Shanghai YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    day = args.date or datetime.now(BJ).strftime("%Y-%m-%d")
    result = audit(day, args.root)
    folder = args.root / "data/quality/sector_mapping" / day[:4] / day[5:7]
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (folder / (day + ".json")).write_text(payload, encoding="utf-8")
    latest = args.root / "data/quality/sector_mapping_latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(payload, encoding="utf-8")
    print(json.dumps({"date": day, "pending": result["pending_count"],
                      "high_priority": result["high_priority_count"],
                      "topics": [x["topic"] for x in result["pending"]]}, ensure_ascii=False))
if __name__ == "__main__":
    main()
