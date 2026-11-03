"""Read live official-source RSS and article bodies. Discovery is NOT verification."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET
from .tools.io import parse_utc

OFFICIAL_FEEDS = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "European Central Bank": "https://www.ecb.europa.eu/rss/press.html",
    "Reserve Bank of Australia": "https://www.rba.gov.au/rss/rss-cb-media-releases.xml",
    "U.S. Bureau of Labor Statistics": "https://www.bls.gov/feed/news_release/rss.xml",
}
ALLOWED_HOSTS = {"www.federalreserve.gov", "www.ecb.europa.eu",
                 "www.rba.gov.au", "www.bls.gov"}
MAX_DOWNLOAD_BYTES = 512_000
MAX_ARTICLES_PER_FEED = 5

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class VisibleParagraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.block = 0
        self.depth = 0
        self.chunks = []
        self.current = []
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            self.block += 1
        if tag == "p":
            self.depth += 1
    def handle_endtag(self, tag):
        if tag == "p" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                paragraph = " ".join(" ".join(self.current).split())
                if len(paragraph) >= 45:
                    self.chunks.append(paragraph)
                self.current = []
        if tag in {"script", "style", "nav", "footer"} and self.block:
            self.block -= 1
    def handle_data(self, text):
        if self.depth and not self.block:
            self.current.append(text)

def allowed_url(url):
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS
            and (parts.port is None or parts.port == 443)
            and not parts.username and not parts.password)

def fetch_public(url, timeout=8):
    """Only fetch explicitly allowlisted public domains; reject redirects and large bodies."""
    if not allowed_url(url):
        raise ValueError("URL is not a permitted official source")
    opener = build_opener(NoRedirect)
    request = Request(url, headers={"User-Agent": "GlobalMarketRadar-research/0.3",
                                    "Accept": "application/rss+xml,application/xml,text/xml,text/html"})
    with opener.open(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"application/rss+xml", "application/xml", "text/xml",
                                "application/atom+xml", "text/html", "application/xhtml+xml"}:
            raise ValueError(f"Unsupported HTTP content type: {content_type}")
        content = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise ValueError("HTTP content size limit exceeded")
        return content

def parsed_date(value):
    if not value:
        return None
    try:
        result = parse_utc(value)
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
            if result.tzinfo is None:
                return None
            result = result.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            return None
    return result

def parse_feed(data, publisher, feed_url, cutoff, limit=MAX_ARTICLES_PER_FEED):
    """Strict as-of filtering; missing publish time cannot be treated as current."""
    root = ET.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom",
          "dc": "http://purl.org/dc/elements/1.1/"}
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//atom:entry", ns)
    result, seen = [], set()
    for item in items:
        title = (item.findtext("title") or item.findtext("atom:title", namespaces=ns) or "").strip()
        link = item.findtext("link") or ""
        if not link:
            node = item.find("atom:link", ns)
            link = node.get("href", "") if node is not None else ""
        link = urljoin(feed_url, link.strip())
        published = (item.findtext("pubDate") or item.findtext("dc:date", namespaces=ns)
                     or item.findtext("atom:published", namespaces=ns)
                     or item.findtext("atom:updated", namespaces=ns))
        at = parsed_date(published)
        if (not title or not allowed_url(link) or not at or at > cutoff
                or at < cutoff - timedelta(hours=72) or link in seen):
            continue
        seen.add(link)
        result.append({"title": title, "publisher": publisher, "url": link,
                       "published_at_utc": at.isoformat(), "source_feed": feed_url,
                       "verification": "rss_only_unverified"})
        if len(result) >= limit:
            break
    return result

def extract_article_text(data):
    parser = VisibleParagraphs()
    parser.feed(data.decode("utf-8", "replace"))
    return " ".join(parser.chunks)[:6500]

def tokens(title):
    return {t for t in re.findall(r"[a-z0-9]{4,}", title.lower())
            if t not in {"about", "after", "with", "from", "that", "this",
                         "their", "today", "update", "press", "release"}}

def mark_possible_related(stories):
    """Shared-title tokens only flag review leads, never assert corroboration."""
    for i, story in enumerate(stories):
        a = tokens(story["title"])
        related = []
        for j, other in enumerate(stories):
            if i == j or story["publisher"] == other["publisher"]:
                continue
            b = tokens(other["title"])
            score = len(a & b) / max(1, len(a | b))
            if len(a & b) >= 3 and score >= 0.4:
                related.append({"source_id": other["id"], "title_similarity": round(score, 3)})
        story["possible_related_independent_sources"] = related
    return stories

def collect_official_research(cutoff_utc, fetcher=fetch_public, feeds=None, max_items_per_feed=5):
    """Fetch real web pages; do not supply these as verified evidence to the model."""
    feeds = feeds or OFFICIAL_FEEDS
    results, errors = [], []
    for publisher, url in feeds.items():
        try:
            if not allowed_url(url):
                raise ValueError("Feed outside allowed host list")
            stories = parse_feed(fetcher(url), publisher, url, cutoff_utc, max_items_per_feed)
        except (HTTPError, URLError, ValueError, TimeoutError, ET.ParseError, OSError) as exc:
            errors.append({"publisher": publisher, "stage": "feed", "error": str(exc)[:240]})
            continue
        for item in stories:
            item["id"] = f"R{len(results)+1}"
            try:
                raw = fetcher(item["url"])
                body = extract_article_text(raw)
                item["article_excerpt"] = body
                item["article_excerpt_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
                item["verification"] = ("article_fetched_unverified" if len(body) >= 100
                                        else "article_text_insufficient_unverified")
            except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
                item["fetch_error"] = str(exc)[:240]
            results.append(item)
    mark_possible_related(results)
    return {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "analysis_cutoff_utc": cutoff_utc.isoformat(),
            "provenance": "official_publisher_rss_and_original_article_urls",
            "disclaimer": ("Article retrieval and title similarity are not independent fact verification; "
                           "manual review is required before a source is used as reported evidence."),
            "sources": results, "errors": errors}

def review_template(research, report_date):
    """Intentionally INVALID until a human fills and checks every source."""
    sources = []
    for item in research["sources"]:
        sources.append({"id": item["id"], "title": item["title"],
                        "publisher": item["publisher"], "url": item["url"],
                        "published_at_utc": item["published_at_utc"],
                        "verification": "needs_human_review", "fact_notes": "",
                        "reviewed_at_utc": ""})
    return {"report_date": report_date, "news_sources": sources,
            "note": "Review the article and replace verification/fact_notes/reviewed_at_utc before use."}
