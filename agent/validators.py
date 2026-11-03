"""Enforce schema, citation integrity, and separation of facts from model output."""
from scripts.render import validate_analysis as validate_html_analysis
from .tools.io import public_sources, valid_https_url

BIASES = {"positive", "negative", "mixed", "watch"}
UNCERTAINTIES = {"high", "medium", "low"}

def validate_generated(doc, report_date, approved_sources, snapshot_sha):
    if not isinstance(doc, dict) or doc.get("report_date") != report_date:
        raise ValueError("Analysis report_date mismatch")
    meta = doc.get("agent_meta")
    if not isinstance(meta, dict) or meta.get("snapshot_sha256") != snapshot_sha:
        raise ValueError("Analysis input snapshot SHA mismatch")
    if doc.get("a_share_bias") not in BIASES or doc.get("uncertainty") not in UNCERTAINTIES:
        raise ValueError("Invalid A-share bias or uncertainty")
    for key in ("market_summary", "a_share_outlook"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise ValueError(f"Missing required analysis field: {key}")
    if not isinstance(doc.get("risks"), list) or not all(isinstance(v, str) for v in doc["risks"]):
        raise ValueError("risks must be an array of strings")
    sectors = doc.get("a_share_sectors")
    if not isinstance(sectors, list) or not all(isinstance(s, dict) and
       all(isinstance(s.get(k), str) and s[k].strip() for k in ("sector", "bias", "reason"))
       and s["bias"] in BIASES for s in sectors):
        raise ValueError("Invalid a_share_sectors")
    expected = public_sources(approved_sources)
    if doc.get("news_sources") != expected:
        raise ValueError("news_sources must exactly match externally reviewed sources")
    urls = [item["url"] for item in expected]
    if doc.get("evidence_urls") != urls or not all(valid_https_url(u) for u in urls):
        raise ValueError("Evidence URLs must come from reviewed sources")
    digest = doc.get("news_digest")
    if not isinstance(digest, dict) or not isinstance(digest.get("items"), list):
        raise ValueError("news_digest must contain items")
    if not expected and (digest["items"] or digest.get("overview")):
        raise ValueError("RSS alone is not verified evidence; digest must be empty")
    known = {s["id"] for s in expected}
    for item in digest["items"]:
        if item.get("importance") not in {"high", "medium", "low"}:
            raise ValueError("Invalid digest importance")
        if not item.get("source_ids") or not set(item["source_ids"]).issubset(known):
            raise ValueError("Digest cites a source that was not reviewed")
    validate_html_analysis(doc)
    return doc
