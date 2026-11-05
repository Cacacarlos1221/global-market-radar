import csv
import json
import tempfile
import unittest
from pathlib import Path
from scripts.curate_data import build, materialize_day

class CuratedDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        p = self.root / "config/instruments.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"assets": [
            {"key": "USD_CNY", "category": "fx", "symbol": "CNY=X", "label": "USD/CNY", "unit": "CNY/USD"},
            {"key": "SSE", "category": "cn_index", "symbol": "000001.SS", "label": "上证综指", "unit": "points"},
            {"key": "CSI300", "category": "cn_index", "symbol": "000300.SS", "label": "沪深300", "unit": "points"}
        ]}), encoding="utf-8")
        date = "2026-11-05"
        self.path = self.root / "data/daily/2026/11/2026-11-05.json"
        self.path.parent.mkdir(parents=True)
        raw = {"report_date": date, "report_timezone": "Asia/Shanghai",
               "collected_at_utc": "2026-11-05T00:18:21Z",
               "news": [{"headline": "Raw RSS"}],
               "quotes": [
                   {"key": "SSE", "category": "cn_index", "status": "ok",
                    "market_date": "2026-11-03", "value": 3608.1,
                    "reference_close": 3638.03, "reference_date": "2026-11-02",
                    "change_pct": -0.8227, "source": "Yahoo"},
                   {"key": "CSI300", "category": "cn_index", "status": "ok",
                    "market_date": "2026-11-04", "value": 4101.33,
                    "reference_close": None, "reference_date": None,
                    "change_pct": None, "source": "Yahoo"}
               ]}
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        folder = self.root / "data/supplements/2026/11/2026-11-05"
        folder.mkdir(parents=True)
        self.supp = folder / "SSE.json"
        url = "https://example.com/source"
        self.supp.write_text(json.dumps({
            "report_date": date, "kind": "source_correction",
            "collected_at_utc": "2026-11-05T00:41:39Z", "source_url": url,
            "quote": {"key": "SSE", "category": "cn_index", "status": "ok",
                      "value": 3686.17, "market_date": "2026-11-04",
                      "reference_close": 3608.1, "reference_date": "2026-11-03",
                      "change_pct": 2.1637, "source": "Source correction", "source_url": url}
        }), encoding="utf-8")
        self.raw_bytes = self.path.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_corrected_json_and_history(self):
        result = build(self.root)
        self.assertEqual((result["daily_files"], result["quote_rows"], result["source_corrected_rows"]), (1, 3, 1))
        p = self.root / "data/curated/daily/2026/11/2026-11-05.json"
        data_bytes = p.read_bytes()
        day = json.loads(data_bytes)
        self.assertEqual(len(day["quotes"]), 3)
        sse = next(q for q in day["quotes"] if q["key"] == "SSE")
        self.assertEqual((sse["value"], sse["raw_value"]), (3686.17, 3608.1))
        self.assertEqual(sse["available_at_utc"], "2026-11-05T00:41:39Z")
        self.assertEqual(sse["revision_kind"], "source_correction")
        self.assertTrue(sse["usable_for_return_analysis"])
        missing = next(q for q in day["quotes"] if q["key"] == "USD_CNY")
        self.assertEqual((missing["status"], missing["value"]), ("missing", None))
        self.assertFalse(missing["usable_for_price_analysis"])
        csi = next(q for q in day["quotes"] if q["key"] == "CSI300")
        self.assertTrue(csi["usable_for_price_analysis"])
        self.assertFalse(csi["usable_for_return_analysis"])
        self.assertEqual(self.path.read_bytes(), self.raw_bytes)
        with (self.root / "data/curated/history/quotes.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3)
        build(self.root)
        self.assertEqual(p.read_bytes(), data_bytes)

    def test_cn_intraday_is_not_final_close_or_final_return(self):
        snapshot = json.loads(self.path.read_text(encoding="utf-8"))
        snapshot["report_date"] = "2026-11-03"
        snapshot["collected_at_utc"] = "2026-11-03T06:44:56+00:00"
        snapshot["quotes"][0]["market_date"] = "2026-11-03"
        snapshot["quotes"][0]["value_kind"] = "daily_close"
        snapshot["quotes"][1]["market_date"] = "2026-11-03"
        p = self.root / "data/daily/2026/11/2026-11-03.json"
        p.write_text(json.dumps(snapshot), encoding="utf-8")
        daily = materialize_day(p, self.root)
        sse = next(q for q in daily["quotes"] if q["key"] == "SSE")
        self.assertIn("unclosed_cn_session_asof", sse["quality_flags"])
        self.assertEqual(sse["value_kind"], "daily_bar_live")
        self.assertEqual(sse["raw_value_kind"], "daily_close")
        self.assertTrue(sse["usable_for_price_analysis"])
        self.assertFalse(sse["usable_for_return_analysis"])

    def test_stale_without_correction_not_model_usable(self):
        self.supp.unlink()
        day = materialize_day(self.path, self.root)
        sse = next(q for q in day["quotes"] if q["key"] == "SSE")
        self.assertIn("stale_vs_cn_index_peer", sse["quality_flags"])
        self.assertFalse(sse["usable_for_price_analysis"])

    def test_source_hash_tracks_changes(self):
        before = materialize_day(self.path, self.root)
        self.supp.write_text(self.supp.read_text() + "\n", encoding="utf-8")
        after = materialize_day(self.path, self.root)
        self.assertNotEqual(before["supplement_sha256"], after["supplement_sha256"])
        self.assertEqual(before["raw_snapshot_sha256"], after["raw_snapshot_sha256"])

if __name__ == "__main__":
    unittest.main()
