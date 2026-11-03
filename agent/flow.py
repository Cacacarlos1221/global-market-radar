"""Executable Stage-2 graph: preflight -> research -> analysis -> critic -> preview."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from scripts.render import render_report
from .critic import critique
from .orchestrator import build_analysis, inputs, report_mode, write_preview
from .research import build_research_queue
from .tools.io import parse_utc

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def run_flow(root, report_date, client=None, evidence_path=None, now_utc=None):
    """Offline mode emits review queue/HTML. Model mode also emits a validated draft."""
    root = Path(root)
    now = now_utc or datetime.now(timezone.utc)
    run_dir = root / "agent/output" / report_date
    if (root / "agent/output" / (report_date + ".analysis.json")).exists():
        raise FileExistsError("An analysis preview exists; do not silently replace an earlier run")
    if run_dir.exists():
        raise FileExistsError(f"Run directory exists; do not silently replace an earlier run: {run_dir}")
    audit = {"flow_version": "v0.2", "report_date": report_date,
             "run_at_utc": now.isoformat(), "mode": report_mode(report_date, now),
             "model_mode": "two_pass_llm" if client is not None else "offline_review_queue",
             "steps": [], "status": "started"}
    def step(name, details):
        audit["steps"].append({"node": name, **details})
    try:
        snapshot, sha, sources, supplements, excluded = inputs(root, report_date, evidence_path, now)
        step("preflight", {"snapshot_sha256": sha, "quotes": len(snapshot["quotes"]),
                           "supplements_included": len(supplements),
                           "supplements_future_excluded": len(excluded)})
        queue = build_research_queue(snapshot, now)
        step("research", {"unverified_leads": len(queue), "human_reviewed_sources": len(sources)})
        dump(run_dir / "research_queue.json", {
            "report_date": report_date,
            "notice": "RSS leads are unverified. Human-reviewed evidence is separate.",
            "candidates": queue,
        })
        if client is None:
            html = render_report(snapshot, None, "../../../index.html")
            (run_dir / "report.preview.html").write_text(html, encoding="utf-8")
            step("render_preview", {"analysis_present": False})
            audit["status"] = "needs_model_and_reviewed_evidence"
            return {"status": audit["status"], "run_dir": str(run_dir),
                    "html": str(run_dir / "report.preview.html"),
                    "research_queue": str(run_dir / "research_queue.json")}
        analysis = build_analysis(root, report_date, client, evidence_path, now)
        step("analyst", {"digest_items": len(analysis["news_digest"]["items"]),
                         "a_share_bias": analysis["a_share_bias"]})
        verdict = critique(client, analysis, snapshot, sources, sha)
        step("critic", verdict)
        html = render_report(snapshot, analysis, "../../../index.html")
        (run_dir / "report.preview.html").write_text(html, encoding="utf-8")
        preview = write_preview(root, report_date, analysis)
        step("render_preview", {"analysis_preview": str(preview),
                                "preview_sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
                                "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest()})
        audit["status"] = "passed_pending_human_approval"
        return {"status": audit["status"], "run_dir": str(run_dir),
                "analysis_preview": str(preview),
                "html": str(run_dir / "report.preview.html"),
                "research_queue": str(run_dir / "research_queue.json")}
    except Exception as exc:
        audit["status"] = "blocked"
        step("failure", {"type": type(exc).__name__, "reason": str(exc)})
        raise
    finally:
        dump(run_dir / "audit.json", audit)
