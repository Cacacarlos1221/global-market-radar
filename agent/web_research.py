"""Best-effort keyless web research. Discovery and extraction DO NOT verify facts."""
import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .tools.io import parse_utc

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_QUERIES = ("Federal Reserve", "US stock market", "China economy", "oil prices")
USER_AGENT = "GlobalMarketRadarResearch/0.3 (+personal research; no redistribution)"
MAX_RESPONSE = 600_000
MAX_TEXT = 5000

def public_https(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return False
    if parts.port not in (None, 443) or parts.hostname.endswith((".local", ".internal")):
        return False
    try:
        ip = ipaddress.ip_address(parts.hostname)
        return ip.is_global
    except ValueError:
        return True

def safe_host(url):
    if not public_https(url):
        raise ValueError("Only public HTTPS article URLs are permitted")
    host = urlsplit(url).hostname
    for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("Destination does not resolve exclusively to public IP addresses")
    return host

class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_host(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch_public(url):
    safe_host(url)
    opener = build_opener(PublicRedirects())
    with opener.open(Request(url, headers={"User-Agent": USER_AGENT,
                                           "Accept": "text/html,application/json"}),
                     timeout=9) as response:
        if not public_https(response.url):
            raise ValueError("Redirected to an untrusted destination")
        mime = response.headers.get("Content-Type", "").lower()
        if not any(x in mime for x in ("text/html", "application/json", "text/plain")):
            raise ValueError("Non-text HTTP response")
        return response.read(MAX_RESPONSE + 1)[:MAX_RESPONSE]

def gdelt_url(query, cutoff):
    if not re.fullmatch(r"[A-Za-z0-9 \-]{3,90}", query):
        raise ValueError("Unsafe or invalid research query")
    params = {"query": f'"{query}" sourcelang:english', "mode": "artlist",
              "format": "json", "maxrecords": 8, "sort": "datedesc",
              "startdatetime": (cutoff - timedelta(hours=40)).strftime("%Y%m%d%H%M%S"),
              "enddatetime": cutoff.strftime("%Y%m%d%H%M%S")}
    return GDELT + "?" + urlencode(params)

def gdelt_seen(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def canonical_domain(url):
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.").lower()

class ArticleText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "h1", "h2", "h3", "blockquote"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts, self.current, self.meta = [], [], [], {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append(tag)
        if tag == "meta":
            name = (attrs.get("property") or attrs.get("name") or "").lower()
            if name:
                self.meta[name] = attrs.get("content", "")
        if tag in self.BLOCK:
            self.current = []
    def handle_data(self, data):
        if not self.SKIP.intersection(self.stack) and any(t in self.BLOCK for t in self.stack):
            self.current.append(data)
    def handle_endtag(self, tag):
        if tag in self.BLOCK and self.current:
            line = re.sub(r"\s+", " ", " ".join(self.current)).strip()
            if len(line) > 45:
                self.parts.append(line)
            self.current = []
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]

def published_from_metadata(meta):
    for key in ("article:published_time", "datepublished", "pubdate", "date", "dc.date.issued"):
        value = meta.get(key)
        if not value:
            continue
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo:
                return date.astimezone(timezone.utc)
        except ValueError:
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
    return None

def extract_article(data, cutoff):
    page = ArticleText()
    page.feed(data.decode("utf-8", errors="replace"))
    published = published_from_metadata(page.meta)
    if published is not None and published > cutoff:
        raise ValueError("Publisher article date is after analysis cutoff")
    body = "\n".join(page.parts)
    if len(body) < 140:
        raise ValueError("Article body unavailable, blocked, or too short")
    return {"excerpt": body[:MAX_TEXT], "content_sha256": hashlib.sha256(data).hexdigest(),
            "published_at_utc": published.isoformat() if published else None,
            "time_basis": "publisher_metadata" if published else "gdelt_first_seen_only"}

def research_web(cutoff_utc, queries=DEFAULT_QUERIES, max_articles=8, fetcher=None):
    """Search news and read publishers; every record remains an UNVERIFIED candidate."""
    fetcher = fetcher or fetch_public
    queries = list(queries)[:6]
    max_articles = min(max(int(max_articles), 1), 20)
    candidates, seen_urls, errors = [], set(), []
    for query in queries:
        try:
            raw = fetcher(gdelt_url(query, cutoff_utc))
            result = json.loads(raw)
            articles = result.get("articles", [])
            if not isinstance(articles, list):
                raise ValueError("GDELT returned malformed article list")
        except Exception as exc:
            errors.append({"query": query, "stage": "discover", "reason": str(exc)[:220]})
            continue
        for item in articles:
            if len(candidates) >= max_articles:
                break
            url = item.get("url")
            observed = gdelt_seen(item.get("seendate"))
            if (not isinstance(url, str) or not public_https(url) or
                    canonical_domain(url) == "news.google.com" or url in seen_urls or
                    observed is None or observed > cutoff_utc):
                continue
            seen_urls.add(url)
            try:
                raw = fetcher(url)
                article = extract_article(raw, cutoff_utc)
            except Exception as exc:
                errors.append({"url": url, "stage": "article", "reason": str(exc)[:220]})
                continue
            candidates.append({
                "id": f"C{len(candidates)+1}", "title": str(item.get("title") or "")[:200],
                "publisher": canonical_domain(url), "url": url,
                "first_seen_at_utc": observed.isoformat(), "discovery_query": query,
                **article, "verification": "unverified_web_text",
            })
        if len(candidates) >= max_articles:
            break
    return {"provider": "GDELT DOC 2.0 + public publisher pages",
            "cutoff_utc": cutoff_utc.isoformat(),
            "articles": candidates, "errors": errors,
            "notice": "Publisher pages may block scraping. No article or claim is independently verified here."}
