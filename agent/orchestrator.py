"""Stage-2 analysis harness: deterministic I/O; LLM only drafts analysis text."""
import json
from datetime import datetime, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo
from .tools.io import data_path, load_snapshot, load_reviewed_sources, parse_utc, public_sources
from .validators import validate_generated

ROOT = Path(__file__).resolve().parents[1]
PROMPT = Path(__file__).with_name("prompts") / "system.md"

def report_mode(report_date, now_utc):
    local = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    return ("preopen" if local.date().isoformat() == report_date and
            local.time() < time(9, 30) else "late_or_replay")

def inputs(root, report_date, evidence_path, now_utc):
    snapshot, snapshot_sha = load_snapshot(root, report_date)
    reviewed = load_reviewed_sources(evidence_path, report_date, now_utc)
    return snapshot, snapshot_sha, reviewed

def plan(root, report_date, evidence_path=None, now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    snapshot, sha, sources = inputs(root, report_date, evidence_path, now)
    return {"report_date": report_date, "mode": report_mode(report_date, now),
            "snapshot_sha256": sha, "quote_count": len(snapshot["quotes"]),
            "unverified_rss_leads": len(snapshot.get("news", [])),
            "reviewed_sources": len(sources),
            "preview_path": str(Path(root) / "agent/output" / (report_date + ".analysis.json")),
            "production_unchanged": True}

def build_analysis(root, report_date, client, evidence_path=None, now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    snapshot, sha, reviewed = inputs(root, report_date, evidence_path, now)
    mode = report_mode(report_date, now)
    context = {
        "report_date": report_date, "run_mode": mode, "run_at_utc": now.isoformat(),
        "fact_snapshot_collected_at_utc": snapshot.get("collected_at_utc"),
        "quotes": snapshot["quotes"],
        "rss_leads_unverified": [
            {k: item.get(k) for k in ("event_id", "headline", "source", "published_at_utc")}
            for item in snapshot.get("news", [])[:25]],
        "reviewed_evidence": [
            {k: s.get(k) for k in ("id", "title", "publisher", "published_at_utc", "fact_notes")}
            for s in reviewed],
        "source_ids_allowed": [s["id"] for s in reviewed],
    }
    system = PROMPT.read_text(encoding="utf-8")
    generated = client.generate_json(system, json.dumps(context, ensure_ascii=False))
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
        "agent_meta": {"harness_version": "v0.1-experimental",
                       "run_mode": mode, "run_at_utc": now.isoformat(),
                       "snapshot_collected_at_utc": snapshot.get("collected_at_utc"),
                       "snapshot_sha256": sha, "evidence_mode": "manual_reviewed_only"},
    }
    if mode != "preopen":
        result["a_share_outlook"] = ("【非盘前生成/回放，不能作为当日开盘前预测】" +
                                      (result["a_share_outlook"] or ""))
    return validate_generated(result, report_date, reviewed, sha)

def write_preview(root, report_date, analysis):
    target = Path(root) / "agent/output" / (report_date + ".analysis.json")
    if target.exists():
        raise FileExistsError(f"Preview exists; review/remove manually before rerunning: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as fh:
        json.dump(analysis, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return target

def publish_reviewed(root, report_date, evidence_path=None, reviewed=False, render=False):
    if not reviewed:
        raise PermissionError("Explicit --reviewed required; automated publishing is not enabled")
    from scripts.pipeline import render_all
    preview = Path(root) / "agent/output" / (report_date + ".analysis.json")
    doc = json.loads(preview.read_text(encoding="utf-8"))
    # Evidence must have existed before the original analysis, not merely at publish time.
    run_at = parse_utc(doc["agent_meta"]["run_at_utc"])
    _, sha, sources = inputs(root, report_date, evidence_path, run_at)
    validate_generated(doc, report_date, sources, sha)
    target = data_path(root, "analysis", report_date)
    if target.exists():
        raise FileExistsError(f"Existing published analysis must not be overwritten: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    if render:
        render_all()
    return target
