import json
import tempfile
import unittest
from pathlib import Path
from scripts.release_check import verify
from scripts.render import render_report

class ReleaseGateTests(unittest.TestCase):
    def test_missing_sources_never_count_as_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = verify("2026-11-04", Path(tmp))
            self.assertFalse(result["complete"])
            self.assertTrue(any("Missing snapshot" in err for err in result["errors"]))

    def test_full_analysis_and_html_pass_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date = "2026-11-04"
            dirname = root / "data/daily/2026/11"
            dirname.mkdir(parents=True)
            quote_keys = ("USD_CNY", "AUD_CNY", "NASDAQ", "SP500", "DOW", "AUD_USD")
            quotes = [{"key": key, "label": key, "status": "ok", "value": 7.0,
                       "market_date": "2026-11-03", "value_kind": "daily_close",
                       "change_pct": 0, "observed_at_utc": "2026-11-03T20:00:00Z"} for key in quote_keys]
            snapshot = {"report_date": date, "collected_at_utc": "2026-11-04T00:15:00Z",
                        "quotes": quotes, "news": []}
            (dirname / (date + ".json")).write_text(json.dumps(snapshot), encoding="utf-8")
            ap = root / "data/analysis/2026/11"
            ap.mkdir(parents=True)
            analysis = {"report_date": date, "market_summary": "Market facts",
                        "a_share_outlook": "Observe", "a_share_bias": "mixed",
                        "news_sources": [{"id": "S1", "url": "https://example.com/article"}],
                        "news_digest": {"overview": "News overview",
                            "items": [{"title": "Important event", "summary": "Verified fact",
                                       "market_impact": "Possible effect", "source_ids": ["S1"]}]}}
            (ap / (date + ".json")).write_text(json.dumps(analysis), encoding="utf-8")
            rp = root / "reports/2026/11"
            rp.mkdir(parents=True)
            (rp / (date + ".html")).write_text(render_report(snapshot, analysis), encoding="utf-8")
            (root / "index.html").write_text(render_report(snapshot, analysis), encoding="utf-8")
            self.assertTrue(verify(date, root)["complete"])
            analysis["news_digest"]["items"] = []
            (ap / (date + ".json")).write_text(json.dumps(analysis), encoding="utf-8")
            self.assertFalse(verify(date, root)["complete"])

if __name__ == "__main__":
    unittest.main()
