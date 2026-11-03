"""Agent analysis node: deterministic inputs, LLM draft, strict reference validation."""
import json
from datetime import datetime, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo
from .research import build_research_queue, summarize_sources
from .tools.io import data_path, load_effective_snapshot, load_reviewed_sources, parse_utc, public_sources
from .validators import validate_generated

ROOT = Path(__file__).resolve().parents[1]
PROMPT = Path(__file__).with_name("prompts") / "system.md"

def report_mode(report_date, now_utc):
    local = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    return ("preopen" if local.date().isoformat() == report_date and
            local.time() < time(9, 30) else "late_or_replay")

def inputs(root, report_date, evidence_path, cutoff_utc):
    snapshot, sha, supplements, excluded = load_effective_snapshot(root, report_date, cutoff_utc)
    reviewed = load_reviewed_sources(evidence_path, report_date, cutoff_utc)
    return snapshot, sha, reviewed, supplements, excluded

def plan(root, report_date, evidence_path=None, now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    snapshot, sha, sources, supplements, excluded = inputs(root, report_date, evidence_path, now)
    queue = build_research_queue(snapshot, now)
    return {"report_date": report_date, "mode": report_mode(report_date, now),
            "snapshot_sha256": sha, "quote_count": len(snapshot["quotes"]),
            "unverified_rss_leads": len(queue),
            "reviewed_sources": len(sources), "included_supplements": len(supplements),
            "excluded_future_supplements": len(excluded),
            "preview_path": str(Path(root) / "agent/output" / (report_date + ".analysis.json")),
            "production_unchanged": True}

def build_analysis(root, report_date, client, evidence_path=None, now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    snapshot, sha, reviewed, supplements, excluded = inputs(root, report_date, evidence_path, now)
    mode = report_mode(report_date, now)
    context = {
        "report_date": report_date, "run_mode": mode, "run_at_utc": now.isoformat(),
        "fact_snapshot_collected_at_utc": snapshot.get("collected_at_utc"),
        "quotes": snapshot["quotes"],
        "excluded_future_supplements": excluded,
        "rss_leads_unverified": [
            {k: item.get(k) for k in ("headline", "publisher_hint", "published_at_utc")}
            for item in build_research_queue(snapshot, now)[:25]],
        "reviewed_evidence": summarize_sources(reviewed),
        "source_ids_allowed": [s["id"] for s in reviewed],
    }
    generated = client.generate_json(PROMPT.read_text(encoding="utf-8"),
                                     json.dumps(context, ensure_ascii=False))
    if any(key in generated for key in ("report_date", "news_sources", "evidence_urls", "agent_meta")):
        raise ValueError("Model must not produce trusted metadata or source catalog")
    result = {
        "report_date": report_date, "generated_at_utc": now.isoformat(),
        "market_summary": generated.get("market_summary"),
        "a_share_bias": generated.get("a_share_bias"),
        "a_share_outlook": generated.get("a_share_outlook"),
        "a_share_sectors": generated.get("a_share_sectors"),
        "risks": generated.get("risks"), "uncertainty": generated.get("uncertainty"),
        "news_digest": generated.get("news_digest"),
        "news_sources": public_sources(reviewed),
        "evidence_urls": [s["url"] for s in reviewed],
        "agent_meta": {"harness_version": "v0.2-flow",
                       "run_mode": mode, "run_at_utc": now.isoformat(),
                       "snapshot_collected_at_utc": snapshot.get("collected_at_utc"),
                       "snapshot_sha256": sha, "supplements": supplements,
                       "excluded_future_supplements": excluded,
                       "evidence_mode": "manual_reviewed_only"},
    }
    if mode != "preopen":
        result["a_share_outlook"] = ("【非盘前生成/回放，不能作为当日开盘前预测】" +
                                      (result["a_share_outlook"] or ""))
    return validate_generated(result, report_date, reviewed, sha)

def write_preview(root, report_date, analysis):
    target = Path(root) / "agent/output" / (report_date + ".analysis.json")
    if target.exists():
        raise FileExistsError(f"Preview exists, explicitly remove it before rerunning: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as fh:
        json.dump(analysis, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return target

def publish_reviewed(root, report_date, evidence_path=None, reviewed=False, render=False):
    if not reviewed:
        raise PermissionError("Explicit --reviewed required; automated publishing is disabled")
    import hashlib
    from scripts.pipeline import render_all
    preview = Path(root) / "agent/output" / (report_date + ".analysis.json")
    doc = json.loads(preview.read_text(encoding="utf-8"))
    audit_path = Path(root) / "agent/output" / report_date / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    preview_records = [x for x in audit.get("steps", []) if x.get("node") == "render_preview"]
    if (audit.get("status") != "passed_pending_human_approval" or
        audit.get("model_mode") != "two_pass_llm" or not preview_records or
        preview_records[-1].get("preview_sha256") != hashlib.sha256(preview.read_bytes()).hexdigest()):
        raise PermissionError("Publishing requires the exact two-pass reviewed preview and matching audit")
    run_at = parse_utc(doc["agent_meta"]["run_at_utc"])
    if audit.get("run_at_utc") != doc["agent_meta"]["run_at_utc"]:
        raise ValueError("Audit timestamp does not match preview")
    _, sha, sources, supplements, excluded = inputs(root, report_date, evidence_path, run_at)
    if doc["agent_meta"].get("supplements") != supplements:
        raise ValueError("Supplement provenance changed since the model generated this analysis")
    if doc["agent_meta"].get("excluded_future_supplements") != excluded:
        raise ValueError("Late supplement inventory changed; rerun review before publishing")
    validate_generated(doc, report_date, sources, sha)
    target = data_path(root, "analysis", report_date)
    if target.exists():
        raise FileExistsError(f"Existing published analysis will not be overwritten: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    if render:
        render_all()
    return target
