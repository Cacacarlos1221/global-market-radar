"""Machine-assisted cross-check: claims stay CANDIDATES until human review."""
import json
import re
from pathlib import Path
from .web_research import canonical_domain

PROMPT = Path(__file__).with_name("prompts") / "research.md"

def normalized(value):
    return re.sub(r"\s+", " ", value).casefold().strip()

def verify_claims(documents, candidate_response):
    index = {article["id"]: article for article in documents}
    confirmed = []
    for claim in candidate_response.get("claims", [])[:8]:
        if not isinstance(claim, dict):
            continue
        statement = claim.get("claim")
        if not isinstance(statement, str) or not statement.strip():
            continue
        found, hosts = [], set()
        for support in claim.get("supports", []):
            if not isinstance(support, dict):
                continue
            source = index.get(support.get("id"))
            quote = support.get("exact_quote")
            if source is None or not isinstance(quote, str) or len(quote.strip()) < 24:
                continue
            if normalized(quote) not in normalized(source["excerpt"]):
                continue
            host = canonical_domain(source["url"])
            if host in hosts:
                continue
            hosts.add(host)
            found.append({"id": source["id"], "exact_quote": quote})
        if len(hosts) >= 2:
            confirmed.append({"claim": statement.strip()[:500], "supports": found,
                              "confidence": "two_independent_domains_candidate_not_fact"})
    return confirmed

def cross_check_with_model(client, research):
    documents = research.get("articles", [])[:10]
    if len({canonical_domain(x["url"]) for x in documents}) < 2:
        return {"claims": [], "evidence_draft": {"report_date": "", "news_sources": []},
                "warning": "At least two readable publisher domains are required"}
    context = [{"id": a["id"], "publisher": a["publisher"],
                "title": a["title"], "excerpt": a["excerpt"][:3600]} for a in documents]
    result = client.generate_json(PROMPT.read_text(encoding="utf-8"),
                                  json.dumps({"sources": context}, ensure_ascii=False))
    if not isinstance(result.get("claims"), list):
        raise ValueError("Research agent must return claims list")
    claims = verify_claims(documents, result)
    notes = {}
    for claim in claims:
        for evidence in claim["supports"]:
            notes.setdefault(evidence["id"], []).append(claim["claim"])
    sources = []
    for article in documents:
        if article["id"] not in notes:
            continue
        sources.append({
            "id": article["id"], "title": article["title"],
            "publisher": article["publisher"], "url": article["url"],
            "published_at_utc": article["published_at_utc"],
            "fact_notes": " | ".join(dict.fromkeys(notes[article["id"]])),
            "verification": "candidate_review_required",
            "reviewed_at_utc": None,
        })
    return {"claims": claims, "evidence_draft": {"report_date": "", "news_sources": sources},
            "warning": "Machine matching verifies quoted text and independent domains, NOT factual accuracy. Human approval is required."}
