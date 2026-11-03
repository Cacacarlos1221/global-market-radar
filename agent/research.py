"""Research queue builder. RSS is discovery only, NOT fact verification."""
import re
from datetime import datetime, timezone
from .tools.io import parse_utc

def normalize_title(title):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(title).lower())).strip()

def build_research_queue(snapshot, cutoff_utc, limit=40):
    """Create a deterministic checklist; discard future/duplicate RSS leads."""
    seen, leads = set(), []
    for item in snapshot.get("news", []):
        if not isinstance(item, dict):
            continue
        published = item.get("published_at_utc")
        if published:
            try:
                if parse_utc(published) > cutoff_utc:
                    continue
            except ValueError:
                continue
        headline = item.get("headline") or ""
        key = normalize_title(headline)
        if not key or key in seen:
            continue
        seen.add(key)
        leads.append({
            "event_id": item.get("event_id"), "topic": item.get("topic"),
            "headline": headline, "publisher_hint": item.get("source"),
            "published_at_utc": published, "url_hint": item.get("url"),
            "review_status": "unverified_rss_lead",
            "next_action": "Read original report or primary filing; record independent evidence",
        })
        if len(leads) >= limit:
            break
    return leads

def summarize_sources(sources):
    """Pass only written fact notes into analysis, not article URLs as 'proof'."""
    return [{k: item.get(k) for k in ("id", "title", "publisher", "published_at_utc", "fact_notes")}
            for item in sources]
