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
