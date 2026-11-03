"""Standalone optional network Research Agent. Writes review candidates, never trusted facts."""
import json
from datetime import datetime, timezone
from pathlib import Path
from .orchestrator import inputs
from .research_agent import cross_check_with_model
from .web_research import research_web

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def run_research(root, report_date, client=None, now_utc=None, max_articles=8, fetcher=None):
    now = now_utc or datetime.now(timezone.utc)
    directory = Path(root) / "agent/research_output" / report_date
    if directory.exists():
        raise FileExistsError(f"Research run exists; archive it before rerun: {directory}")
    audit = {"report_date": report_date, "cutoff_utc": now.isoformat(),
             "mode": "web_and_model" if client else "keyless_web",
             "status": "started"}
    try:
        snapshot, sha, _, supplements, _ = inputs(root, report_date, None, now)
        research = research_web(now, max_articles=max_articles, fetcher=fetcher)
        audit.update({"snapshot_sha256": sha, "articles": len(research["articles"]),
                      "fetch_errors": len(research["errors"])})
        save_json(directory / "publisher_candidates.json", research)
        if client is not None:
            checked = cross_check_with_model(client, research)
            checked["evidence_draft"]["report_date"] = report_date
            checked["evidence_draft"]["research_cutoff_utc"] = now.isoformat()
            save_json(directory / "cross_checked_claims.json",
                      {"claims": checked["claims"], "warning": checked["warning"]})
            save_json(directory / "evidence_REVIEW_REQUIRED.json", checked["evidence_draft"])
            audit["candidate_claims"] = len(checked["claims"])
        audit["status"] = "candidate_review_required"
        return {"research_dir": str(directory), "articles": audit["articles"],
                "network_errors": audit["fetch_errors"],
                "candidate_claims": audit.get("candidate_claims"),
                "status": audit["status"]}
    except Exception as exc:
        audit["status"] = "blocked"
        audit["reason"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        save_json(directory / "audit.json", audit)
