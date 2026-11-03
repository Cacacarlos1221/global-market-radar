"""Read immutable fact snapshots and explicitly reviewed evidence only."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,30}")

def data_path(root, group, date):
    return Path(root) / "data" / group / date[:4] / date[5:7] / (date + ".json")

def load_snapshot(root, date):
    path = data_path(root, "daily", date)
    raw = path.read_bytes()
    doc = json.loads(raw)
    if doc.get("report_date") != date or not isinstance(doc.get("quotes"), list):
        raise ValueError(f"Invalid fact snapshot: {path}")
    return doc, hashlib.sha256(raw).hexdigest()

def valid_https_url(url):
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    parts = urlsplit(url)
    return bool(parts.hostname) and not parts.username and not parts.password

def parse_utc(value):
    if not isinstance(value, str):
        raise ValueError("Expected an ISO-8601 UTC timestamp")
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None or d.utcoffset().total_seconds() != 0:
        raise ValueError(f"Timestamp must be UTC: {value}")
    return d

def load_reviewed_sources(path, report_date, cutoff_utc):
    if path is None:
        return []
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("report_date") != report_date or not isinstance(doc.get("news_sources"), list):
        raise ValueError("Evidence date mismatch or news_sources is not an array")
    ids, urls, result = set(), set(), []
    for source in doc["news_sources"]:
        sid, url = source.get("id"), source.get("url")
        if not isinstance(sid, str) or not ID_PATTERN.fullmatch(sid):
            raise ValueError("Invalid evidence source id")
        if sid in ids or url in urls or not valid_https_url(url):
            raise ValueError("Duplicate or invalid evidence URL/id")
        if source.get("verification") != "reported":
            raise ValueError(f"{sid}: source requires explicit human reviewed status 'reported'")
        if not all(isinstance(source.get(k), str) and source[k].strip()
                   for k in ("title", "publisher", "fact_notes", "reviewed_at_utc")):
            raise ValueError(f"{sid}: missing title, publisher, fact_notes or review timestamp")
        if parse_utc(source["reviewed_at_utc"]) > cutoff_utc:
            raise ValueError(f"{sid}: evidence review happened after analysis cutoff")
        published = source.get("published_at_utc")
        if published is not None and parse_utc(published) > cutoff_utc:
            raise ValueError(f"{sid}: news published after analysis cutoff")
        ids.add(sid)
        urls.add(url)
        result.append(dict(source))
    return result

def public_sources(sources):
    return [{k: s.get(k) for k in ("id", "title", "publisher", "published_at_utc", "url", "verification")}
            for s in sources]
