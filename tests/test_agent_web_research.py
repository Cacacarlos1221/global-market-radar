"""No-network test coverage for GDELT research and manual evidence gating."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from agent.research_runner import candidate_template, run_research
from agent.tools.io import load_reviewed_sources
from agent.web_research import gdelt_url
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)

def write_snapshot(root):
    path = Path(root) / "data/daily/2026/11/2026-11-03.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "report_date": "2026-11-03", "collected_at_utc": "2026-11-03T00:15:00Z",
        "quotes": [], "news": []
    }), encoding="utf-8")

class WebResearchTests(unittest.TestCase):
    def test_web_candidates_are_not_trusted(self):
        article = {"id": "C1", "title": "Public article",
                   "publisher": "example.com", "url": "https://example.com/news",
                   "published_at_utc": None}
        document = candidate_template("2026-11-03", [article])
        self.assertEqual(document["news_sources"][0]["verification"], "needs_human_review")
        self.assertEqual(document["news_sources"][0]["fact_notes"], "")
        with tempfile.TemporaryDirectory() as tmp:
            write_snapshot(tmp)
            with patch("agent.research_runner.research_web", return_value={
                "articles": [article], "errors": [], "provider": "fixture"}):
                result = run_research(tmp, "2026-11-03", now_utc=NOW)
                self.assertEqual(result["provider"], "web")
                self.assertEqual(result["articles"], 1)
                with self.assertRaises(ValueError):
                    load_reviewed_sources(result["evidence_template"], "2026-11-03", NOW)
    def test_no_backdated_online_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_research(tmp, "2026-11-02", now_utc=NOW)
    def test_gdelt_uses_cutoff(self):
        self.assertIn("enddatetime=20261103100000", gdelt_url("Federal Reserve", NOW))

if __name__ == "__main__":
    unittest.main()
