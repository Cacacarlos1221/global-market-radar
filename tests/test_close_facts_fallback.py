"""No-network regression checks for the guaranteed after-close facts safety net."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.close_review import check_release, data_path, render_close
from scripts.close_facts_fallback import create_facts_fallback, factual_review

DAY = "2026-11-09"

def quote(value, day=DAY):
    return {"status": "ok", "market_date": day,
            "change_pct": value, "close": 101.0 + value,
            "reference_close": 101.0, "source": "test same-day K-line"}

class CloseFactsFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = data_path(self.root, "close", DAY)
        self.path.parent.mkdir(parents=True)
        self.raw = {
            "schema_version": "1.1", "report_date": DAY, "market_date": DAY,
            "captured_at_utc": "2026-11-09T07:40:00+00:00",
            "forecast_sha256": "sha-frozen-at-08-14", "forecast_status": "frozen",
            "forecast_frozen_at_utc": "2026-11-09T00:14:16+00:00",
            "source": "test verified close K-line",
            "benchmark": {"name": "沪深300", "quote": quote(0.15)},
            "predicted_groups": [
                {"sector": "半导体", "bias": "positive", "reason": "早盘看多",
                 "components": [{"name": "半导体", "board_name": "半导体",
                    "board_code": "BK1036", "is_proxy": False,
                    "quote": quote(1.25), "stocks": []}],
                 "direction_hit": True, "aggregated_change_pct": 1.25,
                 "excess_vs_csi300_pct": 1.10, "evaluation": "directional"},
                {"sector": "稀土", "bias": "watch", "reason": "等待催化",
                 "components": [{"name": "稀土", "board_name": "稀土永磁",
                    "board_code": "BK0578", "is_proxy": True,
                    "quote": quote(-0.70), "stocks": []}],
                 "direction_hit": None, "aggregated_change_pct": None,
                 "evaluation": "not_scorable"}
            ],
            "hot_sectors": [{"name": "焦炭", "quote": quote(3.2), "stocks": []}],
            "news_clues": [{"headline": "未经正文查验的RSS标题",
                "url": "https://example.com/unverified",
                "published_at_utc": "2026-11-09T03:30:00+00:00"}],
            "warnings": []
        }
        self.path.write_text(json.dumps(self.raw, ensure_ascii=False), encoding="utf-8")
    def tearDown(self):
        self.tmp.cleanup()
    def test_same_day_fact_fallback_publishes_degraded_and_keeps_raw_immutable(self):
        raw_bytes = self.path.read_bytes()
        status = create_facts_fallback(DAY, self.root,
                                       datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(status, "facts_fallback_created")
        f = data_path(self.root, "close_fact_analysis", DAY)
        self.assertTrue(f.exists())
        data = json.loads(f.read_text())
        self.assertEqual(data["source_close_sha256"], hashlib.sha256(raw_bytes).hexdigest())
        self.assertEqual(data["analysis_status"], "facts_only_pending_independent_research")
        self.assertEqual(data["new_events"], [])
        self.assertEqual(data["news_sources"], [])
        self.assertNotIn("未经正文查验的RSS标题", data["summary"])
        self.assertEqual(len(data["attributions"]), 2)
        self.assertIn("相对沪深300+1.10个百分点", data["attributions"][0]["observation"])
        self.assertEqual(create_facts_fallback(DAY, self.root), "facts_fallback_already_exists")
        self.assertEqual(self.path.read_bytes(), raw_bytes)
        self.assertFalse(data_path(self.root, "close_analysis", DAY).exists())
        render_close(self.root)
        result = check_release(DAY, self.root)
        self.assertTrue(result["published"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["status"], "DEGRADED")
        self.assertFalse(result["has_independent_research"])
        self.assertEqual(result["analysis_mode"], "facts_only_fallback")
        html = (self.root / "reports/close/index.html").read_text()
        self.assertIn("目前为自动收盘事实版（DEGRADED）", html)
        self.assertIn("GMR · 收盘事实快报（等待独立新闻研究）", html)
    def test_authored_research_upgrades_same_day_without_deleting_facts(self):
        self.assertEqual(create_facts_fallback(DAY, self.root), "facts_fallback_created")
        f = data_path(self.root, "close_fact_analysis", DAY)
        facts_bytes = f.read_bytes()
        authored = data_path(self.root, "close_analysis", DAY)
        authored.parent.mkdir(parents=True, exist_ok=True)
        authored.write_text(json.dumps({
            "schema_version": "1.1", "report_date": DAY,
            "generated_at_utc": "2026-11-09T09:00:00+00:00",
            "analysis_status": "verified_independent_research",
            "summary": "GMR独立新闻研究已完成；真实K线核验和来源单独审查。",
            "key_findings": [], "attributions": [], "new_events": [],
            "news_sources": [], "next_watch": []
        }, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(create_facts_fallback(DAY, self.root),
                         "independent_research_already_exists")
        render_close(self.root)
        result = check_release(DAY, self.root)
        self.assertTrue(result["published"])
        self.assertTrue(result["complete"])
        self.assertTrue(result["has_independent_research"])
        self.assertEqual(result["analysis_mode"], "independent_research")
        html = (self.root / "reports/close/index.html").read_text()
        self.assertIn("GMR独立新闻研究已完成", html)
        self.assertNotIn("目前为自动收盘事实版（DEGRADED）", html)
        self.assertEqual(f.read_bytes(), facts_bytes)
    def test_malformed_authored_analysis_does_not_block_facts_page(self):
        bad = data_path(self.root, "close_analysis", DAY)
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text('{"report_date":"2026-11-09","summary":""}', encoding="utf-8")
        self.assertEqual(create_facts_fallback(DAY, self.root), "facts_fallback_created")
        render_close(self.root)
        check = check_release(DAY, self.root)
        self.assertTrue(check["published"])
        self.assertFalse(check["has_independent_research"])
        self.assertEqual(check["status"], "DEGRADED")
        self.assertTrue(any("failed validation" in w for w in check["warnings"]))
        self.assertIn("目前为自动收盘事实版", (self.root / "reports/close/index.html").read_text())
        self.assertTrue(bad.exists(), "Malformed independent file stays available for auditing")
    def test_no_fact_data_never_forges_daily_report(self):
        self.path.unlink()
        self.assertIsNone(factual_review(DAY, self.root))
        self.assertEqual(create_facts_fallback(DAY, self.root),
                         "no_valid_same_day_close_facts")
        self.assertFalse(data_path(self.root, "close_fact_analysis", DAY).exists())
        self.path.write_text(json.dumps({**self.raw, "market_date": "2026-11-06"}))
        self.assertEqual(create_facts_fallback(DAY, self.root),
                         "no_valid_same_day_close_facts")
        self.assertFalse(data_path(self.root, "close_fact_analysis", DAY).exists())
    def test_stale_quotes_and_unverified_news_are_not_published_as_facts(self):
        self.raw["benchmark"]["quote"] = quote(0.1, "2026-11-06")
        self.raw["predicted_groups"] = []
        self.raw["hot_sectors"] = []
        self.path.write_text(json.dumps(self.raw))
        self.assertEqual(create_facts_fallback(DAY, self.root),
                         "no_valid_same_day_close_facts")

if __name__ == "__main__":
    unittest.main()
