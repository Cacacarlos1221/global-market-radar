"""Read sealed daily facts and reviewed sources, honoring the analysis cutoff."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,30}")

def data_path(root, group, date):
    return Path(root) / "data" / group / date[:4] / date[5:7] / (date + ".json")

def parse_utc(value):
    if not isinstance(value, str):
        raise ValueError("Expected an ISO-8601 UTC timestamp")
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None or d.utcoffset().total_seconds() != 0:
        raise ValueError(f"Timestamp must be UTC: {value}")
    return d

def load_snapshot(root, date):
    path = data_path(root, "daily", date)
    raw = path.read_bytes()
    doc = json.loads(raw)
    if doc.get("report_date") != date or not isinstance(doc.get("quotes"), list):
        raise ValueError(f"Invalid fact snapshot: {path}")
    return doc, hashlib.sha256(raw).hexdigest()

def load_effective_snapshot(root, date, cutoff_utc):
    """Mirror main's supplements, excluding anything captured after this analysis."""
    doc, raw_sha = load_snapshot(root, date)
    if parse_utc(doc["collected_at_utc"]) > cutoff_utc:
        raise ValueError("Fact snapshot was collected after the requested analysis cutoff")
    effective = dict(doc, quotes=[dict(x) for x in doc["quotes"]], supplements=[])
    included, excluded = [], []
    folder = Path(root) / "data/supplements" / date[:4] / date[5:7] / date
    for path in sorted(folder.glob("*.json")):
        raw = path.read_bytes()
        record = json.loads(raw)
        if record.get("report_date") != date or "collected_at_utc" not in record:
            raise ValueError(f"Malformed supplement: {path}")
        captured = parse_utc(record["collected_at_utc"])
        if captured > cutoff_utc:
            excluded.append({"key": path.stem, "collected_at_utc": record["collected_at_utc"]})
            continue
        quote = record.get("quote") or {}
        if quote.get("key") != path.stem or quote.get("status") != "ok" or quote.get("value") is None:
            raise ValueError(f"Malformed supplement quote: {path}")
        if record.get("base_snapshot_collected_at_utc", doc["collected_at_utc"]) != doc["collected_at_utc"]:
            raise ValueError(f"Supplement references a different base snapshot: {path}")
        value = dict(quote, supplement_collected_at_utc=record["collected_at_utc"])
        existing = {item["key"]: i for i, item in enumerate(effective["quotes"])}
        if value["key"] in existing:
            index = existing[value["key"]]
            if effective["quotes"][index].get("status") == "ok":
                raise ValueError(f"Supplement would overwrite an existing valid quote: {path}")
            effective["quotes"][index] = value
        elif value["key"] == "USD_CNY":
            effective["quotes"].insert(0, value)
        else:
            effective["quotes"].append(value)
        supplement = {"key": value["key"], "collected_at_utc": record["collected_at_utc"]}
        effective["supplements"].append(supplement)
        included.append(dict(supplement, sha256=hashlib.sha256(raw).hexdigest()))
    return effective, raw_sha, included, excluded

def valid_https_url(url):
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    parts = urlsplit(url)
    return bool(parts.hostname) and not parts.username and not parts.password

def load_reviewed_sources(path, report_date, cutoff_utc):
    """Trusted input means a reviewer actually read the cited source before cutoff."""
    if path is None:
        return []
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("report_date") != report_date or not isinstance(doc.get("news_sources"), list):
        raise ValueError("Evidence date mismatch or news_sources is not an array")
    ids, urls, result = set(), set(), []
    for source in doc["news_sources"]:
        if not isinstance(source, dict):
            raise ValueError("Invalid reviewed news source")
        sid, url = source.get("id"), source.get("url")
        if not isinstance(sid, str) or not ID_PATTERN.fullmatch(sid):
            raise ValueError("Invalid evidence source id")
        if sid in ids or url in urls or not valid_https_url(url):
            raise ValueError("Duplicate or invalid evidence URL/id")
        if source.get("verification") != "reported":
            raise ValueError(f"{sid}: requires explicit human-reviewed 'reported' status")
        if not all(isinstance(source.get(k), str) and source[k].strip()
                   for k in ("title", "publisher", "fact_notes", "reviewed_at_utc")):
            raise ValueError(f"{sid}: missing title/publisher/fact_notes/review time")
        if parse_utc(source["reviewed_at_utc"]) > cutoff_utc:
            raise ValueError(f"{sid}: reviewed after analysis cutoff")
        if source.get("published_at_utc") is not None and parse_utc(source["published_at_utc"]) > cutoff_utc:
            raise ValueError(f"{sid}: published after analysis cutoff")
        ids.add(sid)
        urls.add(url)
        result.append(dict(source))
    return result

def public_sources(sources):
    return [{k: item.get(k) for k in ("id", "title", "publisher", "published_at_utc", "url", "verification")}
            for item in sources]
