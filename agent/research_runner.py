"""Keyless public research -> review template; optional LLM cross-check stays untrusted."""
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .live_research import collect_official_research, review_template
from .orchestrator import inputs
from .research_agent import cross_check_with_model
from .web_research import research_web

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def candidate_template(report_date, articles):
    """No machine-generated document is allowed to claim human verification."""
    return {"report_date": report_date, "news_sources": [{
        "id": a["id"], "title": a["title"], "publisher": a["publisher"],
        "url": a["url"], "published_at_utc": a.get("published_at_utc"),
        "verification": "needs_human_review", "fact_notes": "",
        "reviewed_at_utc": "",
    } for a in articles],
        "note": "Review the original publisher pages. Fill fact_notes/reviewed_at_utc and set verification=reported only after human review."}

def run_research(root, report_date, provider="web", client=None, now_utc=None,
                 max_articles=8, fetcher=None, feeds=None):
    """Live sources may only be collected for the current Beijing report date.

    This avoids treating material retrieved *today* as if it was observed for a
    historical morning report. Individual article dates are also cutoff-filtered.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Research cutoff must be timezone-aware")
    if report_date != now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat():
        raise ValueError("Live research cannot be backdated as a historical as-of run")
    if provider not in ("official", "web"):
        raise ValueError("Unknown research provider")
    if client is not None and provider != "web":
        raise ValueError("Model-assisted corroboration requires provider='web'")
    directory = Path(root) / "agent/research_output" / report_date / provider
    if directory.exists():
        raise FileExistsError(f"Research output exists; archive it before rerunning: {directory}")
    audit = {"report_date": report_date, "cutoff_utc": now.isoformat(),
             "provider": provider, "model_assisted": client is not None, "status": "started"}
    try:
        snapshot, sha, _, supplements, _ = inputs(root, report_date, None, now)
        audit.update({"snapshot_sha256": sha, "quotes": len(snapshot["quotes"]),
                      "included_supplements": len(supplements)})
        if provider == "official":
            research = collect_official_research(
                now, fetcher=fetcher or __import__(
                    "agent.live_research", fromlist=["fetch_public"]).fetch_public,
                feeds=feeds)
            articles = research["sources"]
            draft = review_template(research, report_date)
            output_name = "official_sources.json"
        else:
            research = research_web(now, max_articles=max_articles, fetcher=fetcher)
            articles = research["articles"]
            draft = candidate_template(report_date, articles)
            output_name = "publisher_candidates.json"
            if client is not None:
                reviewed = cross_check_with_model(client, research)
                draft = reviewed["evidence_draft"]
                draft["report_date"] = report_date
                draft["research_cutoff_utc"] = now.isoformat()
                save_json(directory / "machine_claims_REVIEW_REQUIRED.json", {
                    "claims": reviewed["claims"], "warning": reviewed["warning"]})
                audit["machine_correlated_claims"] = len(reviewed["claims"])
        save_json(directory / output_name, research)
        save_json(directory / "evidence_REVIEW_REQUIRED.json", draft)
        audit.update({"candidate_articles": len(articles), "fetch_errors": len(research["errors"]),
                      "status": "candidate_review_required"})
        return {"status": audit["status"], "provider": provider,
                "research_dir": str(directory), "articles": len(articles),
                "network_errors": len(research["errors"]),
                "machine_correlated_claims": audit.get("machine_correlated_claims", 0),
                "evidence_template": str(directory / "evidence_REVIEW_REQUIRED.json")}
    except Exception as exc:
        audit["status"] = "blocked"
        audit["reason"] = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        save_json(directory / "audit.json", audit)
