"""Regression tests for append-only morning quote recovery and no partial HTML."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from scripts.backfill_missing import recover
from scripts.backfill_quote import backfill_quote

DAY = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()

def make_snapshot(root):
    file = root / "data/daily" / DAY[:4] / DAY[5:7] / (DAY + ".json")
    file.parent.mkdir(parents=True, exist_ok=True)
    content = {"report_date": DAY, "collected_at_utc": "2026-11-04T00:05:00+00:00",
               "quotes": [
                   {"key": "USD_CNY", "status": "unavailable"},
                   {"key": "AUD_CNY", "status": "ok", "value": 4.2}
               ]}
    file.write_text(json.dumps(content), encoding="utf-8")
    return file

class MissingQuoteRecoveryTests(unittest.TestCase):
    def test_only_missing_assets_are_retried(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_snapshot(root)
            supplement = root / "data/supplements" / DAY[:4] / DAY[5:7] / DAY / "NASDAQ.json"
            supplement.parent.mkdir(parents=True)
            supplement.write_text('{"existing":true}', encoding="utf-8")
            with patch("scripts.backfill_missing.backfill_quote", return_value=True) as mock:
                result = recover(DAY, root)
            self.assertEqual(result["report_date"], DAY)
            self.assertIn("USD_CNY", result["attempted"])
            self.assertIn("AUD_CNY: original quote available", result["skipped"])
            self.assertIn("NASDAQ: already supplemented", result["skipped"])
            self.assertEqual(len(result["recovered"]), len(result["attempted"]))
            self.assertTrue(all(k.get("render") is False for _, k in mock.call_args_list))

    def test_backfill_does_not_publish_unanalyzed_html(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            snapshot = make_snapshot(root)
            original = snapshot.read_bytes()
            config = root / "config/instruments.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"assets": [
                {"key": "USD_CNY", "symbol": "CNY=X", "label": "美元/人民币",
                 "category": "fx", "unit": "CNY/USD"}
            ]}), encoding="utf-8")
            quote = {"key": "USD_CNY", "status": "ok", "value": 6.8,
                     "unit": "CNY/USD", "symbol": "CNY=X", "label": "美元/人民币",
                     "category": "fx", "market_date": DAY,
                     "observed_at_utc": "2026-11-04T00:20:00+00:00",
                     "source": "unit_test", "value_kind": "intraday_observation"}
            with patch("scripts.backfill_quote.ROOT", root), \
                 patch("scripts.backfill_quote.collect_quotes", return_value=[quote]), \
                 patch("scripts.backfill_quote.render_all") as render_mock:
                self.assertTrue(backfill_quote("USD_CNY", DAY))
                render_mock.assert_not_called()
                self.assertFalse(backfill_quote("USD_CNY", DAY))
            supplement = root / "data/supplements" / DAY[:4] / DAY[5:7] / DAY / "USD_CNY.json"
            self.assertTrue(supplement.is_file())
            self.assertEqual(snapshot.read_bytes(), original)
            self.assertFalse((root / "index.html").exists())

    def test_existing_but_incomplete_analysis_is_not_rendered(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_snapshot(root)
            cfg = root / "config/instruments.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({"assets": [
                {"key": "USD_CNY", "symbol": "CNY=X", "label": "USD/CNY",
                 "category": "fx", "unit": "CNY/USD"}
            ]}), encoding="utf-8")
            a = root / "data/analysis" / DAY[:4] / DAY[5:7] / (DAY + ".json")
            a.parent.mkdir(parents=True)
            a.write_text(json.dumps({"report_date": DAY,
                                     "market_summary": "Still researching news"}), encoding="utf-8")
            quote = {"key": "USD_CNY", "status": "ok", "value": 6.8,
                     "unit": "CNY/USD", "source": "unit_test",
                     "observed_at_utc": "2026-11-04T00:20:00Z"}
            with patch("scripts.backfill_quote.ROOT", root), \
                 patch("scripts.backfill_quote.collect_quotes", return_value=[quote]), \
                 patch("scripts.backfill_quote.render_all") as render_mock:
                self.assertTrue(backfill_quote("USD_CNY", DAY))
                render_mock.assert_not_called()
            self.assertFalse((root / "index.html").exists())

if __name__ == "__main__":
    unittest.main()
