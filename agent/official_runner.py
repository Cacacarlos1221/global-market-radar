"""Separate keyless official-source discovery; not a trusted fact source."""
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .live_research import collect_official_research, review_template

def run_official_research(root, report_date, now_utc=None, fetcher=None, feeds=None):
    now = now_utc or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if report_date != today:
        raise ValueError("Official live research only supports today's Beijing date")
    target = Path(root) / "agent/output/research" / report_date
    if target.exists():
        raise FileExistsError(f"Research already exists; review or archive first: {target}")
    kwargs = {}
    if fetcher is not None:
        kwargs["fetcher"] = fetcher
    if feeds is not None:
        kwargs["feeds"] = feeds
    research = collect_official_research(now, **kwargs)
    draft = review_template(research, report_date)
    target.mkdir(parents=True, exist_ok=False)
    for filename, value in (("official_sources.json", research), ("review_template.json", draft)):
        (target / filename).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "retrieved_unverified", "reports": len(research["sources"]),
            "errors": len(research["errors"]),
            "sources": str(target / "official_sources.json"),
            "review_template": str(target / "review_template.json"),
            "note": "Official article retrieval is not human fact verification"}
