"""Isolated tests: no real network, no model secret, no source auto-approval."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from agent.live_research import (allowed_url, collect_official_research,
                                 extract_article_text, parse_feed, review_template)
from agent.model_client import load_local_env
from agent.research_runner import run_research
from agent.tools.io import load_reviewed_sources

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
FED_FEED = "https://www.federalreserve.gov/feeds/press_all.xml"
ECB_FEED = "https://www.ecb.europa.eu/rss/press.html"
FED_ARTICLE = "https://www.federalreserve.gov/newsevents/pressreleases/test.htm"
ECB_ARTICLE = "https://www.ecb.europa.eu/press/test.html"
STORY = ("<rss><channel><item><title>Monetary policy decision update</title>"
         "<link>%s</link><pubDate>Tue, 03 Nov 2026 08:00:00 GMT</pubDate></item>"
         "<item><title>Future information must be rejected</title><link>%s</link>"
         "<pubDate>Wed, 04 Nov 2026 08:00:00 GMT</pubDate></item></channel></rss>")

def fake_fetch(url):
    if url == FED_FEED:
        return (STORY % (FED_ARTICLE, FED_ARTICLE + "?future")).encode()
    if url == ECB_FEED:
        return (STORY % (ECB_ARTICLE, ECB_ARTICLE + "?future")).encode()
    if url in (FED_ARTICLE, ECB_ARTICLE):
        return ("<html><body><p>" +
                "A sample long paragraph containing source text for research only. " * 4 +
                "</p></body></html>").encode()
    raise AssertionError(f"Unexpected URL: {url}")

class AgentResearchTests(unittest.TestCase):
    def test_url_allowlist_disallows_redirector_and_local_addresses(self):
        for url in ("https://news.google.com/rss", "http://www.federalreserve.gov/",
                    "https://www.federalreserve.gov.evil.test/", "https://127.0.0.1/",
                    "https://user:pass@www.ecb.europa.eu/news", "https://www.bls.gov:444/"):
            self.assertFalse(allowed_url(url), url)
        self.assertTrue(allowed_url(FED_ARTICLE))
    def test_live_feed_filters_future_and_missing_date(self):
        items = parse_feed(fake_fetch(FED_FEED), "Fed", FED_FEED, NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], FED_ARTICLE)
    def test_source_retrieval_remains_unverified(self):
        result = collect_official_research(NOW, fetcher=fake_fetch,
                                          feeds={"Fed": FED_FEED, "ECB": ECB_FEED})
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["errors"], [])
        self.assertTrue(all(s["verification"] == "article_fetched_unverified" for s in result["sources"]))
        self.assertTrue(all(s.get("article_excerpt_sha256") for s in result["sources"]))
        self.assertTrue(all("possible_related_independent_sources" in s for s in result["sources"]))
        template = review_template(result, "2026-11-03")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review_template.json"
            path.write_text(json.dumps(template))
            with self.assertRaises(ValueError):
                load_reviewed_sources(path, "2026-11-03", NOW)
    def test_bad_feed_degrades_without_aborting_all_research(self):
        def fetcher(url):
            if url == ECB_FEED:
                raise OSError("Source unavailable")
            return fake_fetch(url)
        result = collect_official_research(NOW, fetcher=fetcher,
                                          feeds={"Fed": FED_FEED, "ECB": ECB_FEED})
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(len(result["errors"]), 1)
    def test_review_workflow_writes_files_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = run_research(Path(tmp), "2026-11-03", NOW, fake_fetch, {"Fed": FED_FEED})
            self.assertEqual(output["reports"], 1)
            self.assertEqual(output["status"], "retrieved_unverified")
            self.assertTrue(Path(output["sources"]).exists())
            with self.assertRaises(FileExistsError):
                run_research(Path(tmp), "2026-11-03", NOW, fake_fetch, {"Fed": FED_FEED})
    def test_retroactive_live_research_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_research(Path(tmp), "2026-11-02", NOW, fake_fetch, {"Fed": FED_FEED})
    def test_article_parser_excludes_navigation_script(self):
        html = b"<nav><p>Navigation should be ignored even when lengthy filler text exists.</p></nav><script>bad()</script><p>Real original paragraph with quite enough characters to keep this factual quotation.</p>"
        self.assertIn("Real original", extract_article_text(html))
        self.assertNotIn("Navigation", extract_article_text(html))
    def test_local_env_loads_without_overwriting_real_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("MARKET_AGENT_MODEL=example-model\nMARKET_AGENT_API_KEY='sample-not-real'\n")
            with patch.dict(os.environ, {"MARKET_AGENT_MODEL": "existing"}, clear=True):
                load_local_env(path)
                self.assertEqual(os.getenv("MARKET_AGENT_MODEL"), "existing")
                self.assertEqual(os.getenv("MARKET_AGENT_API_KEY"), "sample-not-real")

if __name__ == "__main__":
    unittest.main()
