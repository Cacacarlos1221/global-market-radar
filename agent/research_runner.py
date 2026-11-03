"""Public-source research command; separate from editorial approval."""
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .live_research import collect_official_research, review_template

def run_research(root, report_date, now_utc=None, fetcher=None, feeds=None):
    now = now_utc or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if report_date != today:
        raise ValueError("Live research can only run for today's Beijing date, not historical as-of replay")
    target = Path(root) / "agent/output/research" / report_date
    if target.exists():
        raise FileExistsError(f"Research already exists; review/archive first: {target}")
    options = {}
    if fetcher is not None:
        options["fetcher"] = fetcher
    if feeds is not None:
        options["feeds"] = feeds
    research = collect_official_research(now, **options)
    draft = review_template(research, report_date)
    target.mkdir(parents=True, exist_ok=False)
    def write(name, doc):
        (target / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write("official_sources.json", research)
    write("review_template.json", draft)
    return {"status": "retrieved_unverified", "reports": len(research["sources"]),
            "errors": len(research["errors"]),
            "sources": str(target / "official_sources.json"),
            "review_template": str(target / "review_template.json"),
            "note": "Review original pages and fill fact_notes/reviewed_at_utc; never auto-approve"}
