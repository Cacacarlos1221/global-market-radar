import json
import tempfile
import unittest
from pathlib import Path
from scripts.pipeline import with_supplements
from scripts.render import render_report

class SupplementTests(unittest.TestCase):
    def test_supplement_merges_without_modifying_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = "2026-11-03"
            original = {"report_date": day, "collected_at_utc": "2026-11-03T00:15:00Z",
                        "quotes": [{"key": "AUD_CNY", "label": "澳元/人民币",
                                    "status": "ok", "value": 4.5, "change_pct": 0.0,
                                    "market_date": day, "value_kind": "intraday_observation",
                                    "observed_at_utc": "2026-11-03T00:14:00Z"}], "news": []}
            folder = root / "data/supplements/2026/11/2026-11-03"
            folder.mkdir(parents=True)
            quote = {"key": "USD_CNY", "label": "美元/人民币", "status": "ok",
                     "value": 7.2, "change_pct": 0.1, "market_date": day,
                     "value_kind": "intraday_observation",
                     "observed_at_utc": "2026-11-03T09:10:00Z"}
            (folder / "USD_CNY.json").write_text(json.dumps({
                "report_date": day, "collected_at_utc": "2026-11-03T09:12:00Z",
                "quote": quote
            }), encoding="utf-8")
            merged = with_supplements(original, root)
            self.assertEqual(merged["quotes"][0]["key"], "USD_CNY")
            self.assertEqual(merged["quotes"][0]["value"], 7.2)
            self.assertEqual(len(original["quotes"]), 1)
            self.assertIn("补采UTC", render_report(merged))
    def test_authoritative_source_correction_is_versioned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data/supplements/2026/11/2026-11-04"
            folder.mkdir(parents=True)
            official = "https://www.sse.com.cn/market/sseindex/overview/"
            record = {"report_date": "2026-11-04", "kind": "source_correction",
                      "source_url": official, "collected_at_utc": "2026-11-04T01:00:00Z",
                      "quote": {"key": "SSE", "label": "上证综指",
                                "category": "cn_index", "status": "ok",
                                "market_date": "2026-11-03", "value": 3608.10,
                                "change_pct": -0.8227, "value_kind": "official_daily_close",
                                "observed_at_utc": None, "source_url": official}}
            (folder / "SSE.json").write_text(json.dumps(record), encoding="utf-8")
            original = {"report_date": "2026-11-04", "collected_at_utc": "2026-11-04T00:36:00Z",
                        "quotes": [{"key": "SSE", "category": "cn_index", "status": "ok",
                                    "market_date": "2026-11-02", "value": 3638.03}], "news": []}
            merged = with_supplements(original, root)
            self.assertEqual(merged["quotes"][0]["value"], 3608.10)
            self.assertEqual(original["quotes"][0]["value"], 3638.03)
            self.assertEqual(merged["quote_revisions"][0]["old_market_date"], "2026-11-02")
            html = render_report(merged)
            self.assertIn("来源修正", html)
            self.assertIn("官方来源", html)
    def test_reject_correction_without_newer_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data/supplements/2026/11/2026-11-04"
            folder.mkdir(parents=True)
            (folder / "SSE.json").write_text(json.dumps({
                "report_date": "2026-11-04", "kind": "source_correction",
                "source_url": "https://www.sse.com.cn/market/sseindex/overview/",
                "collected_at_utc": "2026-11-04T01:00:00Z",
                "quote": {"key": "SSE", "status": "ok", "market_date": "2026-11-02",
                          "value": 999, "source_url": "https://www.sse.com.cn/market/sseindex/overview/"}
            }), encoding="utf-8")
            original = {"report_date": "2026-11-04",
                        "quotes": [{"key": "SSE", "status": "ok",
                                     "market_date": "2026-11-02", "value": 3638.03}]}
            with self.assertRaises(ValueError):
                with_supplements(original, root)
    def test_existing_valid_quote_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "data/supplements/2026/11/2026-11-03"
            folder.mkdir(parents=True)
            (folder / "USD_CNY.json").write_text(json.dumps({
                "report_date": "2026-11-03", "collected_at_utc": "2026-11-03T09:12:00Z",
                "quote": {"key": "USD_CNY", "status": "ok", "value": 7}
            }), encoding="utf-8")
            original = {"report_date": "2026-11-03",
                        "quotes": [{"key": "USD_CNY", "status": "ok", "value": 7.1}]}
            with self.assertRaises(ValueError):
                with_supplements(original, root)

if __name__ == "__main__":
    unittest.main()
