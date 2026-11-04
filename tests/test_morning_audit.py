"""Guard against fake success and lost forecast freezing in the morning pipeline."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.morning_audit import audit
from scripts.close_review import freeze_forecast, BJ
from scripts.render import render_report

DAY = "2026-11-05"
NOW = datetime(2026, 11, 5, 9, 5, tzinfo=BJ)

def fixture(root):
    raw = root / "data/daily/2026/11/2026-11-05.json"
    raw.parent.mkdir(parents=True)
    quotes = [{"key": k, "label": k, "status": "ok", "value": 7.0,
               "market_date": "2026-11-04", "observed_at_utc": "2026-11-04T20:00:00Z",
               "value_kind": "daily_close", "source": "fixture", "change_pct": 0.2}
              for k in ("USD_CNY", "AUD_CNY", "NASDAQ", "SP500", "DOW", "AUD_USD")]
    snapshot = {"report_date": DAY, "quotes": quotes,
                "collected_at_utc": "2026-11-05T00:15:00+00:00", "news": []}
    raw.write_text(json.dumps(snapshot), encoding="utf-8")
    path = root / "data/analysis/2026/11/2026-11-05.json"
    path.parent.mkdir(parents=True)
    analysis = {"report_date": DAY, "generated_at_utc": "2026-11-05T00:40:00Z",
                "market_summary": "Morning summary", "a_share_outlook": "Observe",
                "a_share_bias": "watch",
                "a_share_sectors": [{"sector": "半导体", "bias": "watch", "reason": "观察"}],
                "news_sources": [{"id": "S1", "url": "https://example.com/news"}],
                "news_digest": {"overview": "Verified major story",
                    "items": [{"title": "Headline", "summary": "Evidence", "market_impact": "Possible impact",
                               "source_ids": ["S1"]}]}}
    path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    out = root / "reports/2026/11/2026-11-05.html"
    out.parent.mkdir(parents=True)
    out.write_text(render_report(snapshot, analysis), encoding="utf-8")
    (root / "index.html").write_text(render_report(snapshot, analysis), encoding="utf-8")
    return path

class MorningAuditTests(unittest.TestCase):
    def test_no_snapshot_or_analysis_fails(self):
        with tempfile.TemporaryDirectory() as d:
            report = audit(DAY, Path(d), NOW)
            self.assertFalse(report["report_published"])
            self.assertEqual(report["report_status"], "FAILED")

    def test_full_report_without_freeze_still_publishes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            report = audit(DAY, root, NOW)
            self.assertTrue(report["report_published"], report["errors"])
            self.assertEqual(report["report_status"], "COMPLETE")
            self.assertEqual(report["forecast_state"], "MISSING")
            self.assertFalse(report["forecast_eligible_for_scoring"])

    def test_available_supplement_clears_missing_quote_warning(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            snap = root / "data/daily/2026/11/2026-11-05.json"
            data = json.loads(snap.read_text(encoding="utf-8"))
            data["quotes"][0]["status"] = "unavailable"
            data["quotes"][0]["value"] = None
            snap.write_text(json.dumps(data), encoding="utf-8")
            folder = root / "data/supplements/2026/11/2026-11-05"
            folder.mkdir(parents=True)
            fixed = dict(data["quotes"][0])
            fixed.update({"status": "ok", "value": 6.7, "source": "validated supplement"})
            (folder / "USD_CNY.json").write_text(json.dumps({
                "report_date": DAY, "collected_at_utc": "2026-11-05T00:42:00+00:00",
                "quote": fixed
            }), encoding="utf-8")
            report = audit(DAY, root, NOW)
            self.assertTrue(report["report_published"], report["errors"])
            self.assertEqual(report["quotes"]["USD_CNY"]["status"], "ok")
            self.assertIsNotNone(report["quotes"]["USD_CNY"]["supplement_collected_at_utc"])
            self.assertFalse(any("USD_CNY unavailable" in x for x in report["warnings"]))

    def test_freeze_content_hash_and_time_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            analysis = fixture(root)
            cfg = root / "config/sector_watchlist.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text('{"tracks":[]}', encoding="utf-8")
            self.assertEqual(freeze_forecast(DAY, root, datetime(2026, 11, 5, 8, 50, tzinfo=BJ)), "frozen")
            good = audit(DAY, root, NOW)
            self.assertTrue(good["report_published"], good["errors"])
            self.assertTrue(good["forecast_eligible_for_scoring"])
            self.assertEqual(good["forecast_state"], "FROZEN")
            old = analysis.read_text(encoding="utf-8")
            analysis.write_text(old + " ", encoding="utf-8")
            mismatch = audit(DAY, root, NOW)
            self.assertTrue(mismatch["report_published"])
            self.assertEqual(mismatch["forecast_state"], "MISMATCH_ANALYSIS_HASH")
            self.assertFalse(mismatch["forecast_eligible_for_scoring"])

    def test_frozen_after_open_never_eligible(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            analysis = fixture(root)
            forecast = root / "data/forecasts/2026/11/2026-11-05.json"
            forecast.parent.mkdir(parents=True)
            forecast.write_text(json.dumps({
                "report_date": DAY, "frozen_at_utc": "2026-11-05T01:35:00+00:00",
                "analysis_sha256": hashlib.sha256(analysis.read_bytes()).hexdigest(),
                "a_share_sectors": [{"sector": "半导体"}]
            }), encoding="utf-8")
            report = audit(DAY, root, NOW)
            self.assertTrue(report["report_published"])
            self.assertEqual(report["forecast_state"], "INVALID_FREEZE_TIME")
            self.assertFalse(report["forecast_eligible_for_scoring"])

if __name__ == "__main__":
    unittest.main()
