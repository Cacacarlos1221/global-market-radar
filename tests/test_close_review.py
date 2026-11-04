"""离线测试：冻结时点、组合样本、不可覆盖、新闻引用与XSS防护。"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from scripts.close_review import BJ, collect_close, data_path, find_tracks, freeze_forecast
from scripts.close_render import render_close_report, validate_close_analysis

DAY = "2026-11-05"
TRACKS = {
    "schema_version": "1.0",
    "tracks": [
        {"key": "semiconductor", "name": "半导体", "terms": ["半导体"],
         "board_names": ["半导体"], "board_type": "industry",
         "stocks": [["688981", "1", "中芯国际"]]},
        {"key": "server", "name": "AI服务器", "terms": ["AI服务器"],
         "board_names": ["AI服务器", "服务器"], "board_type": "concept",
         "stocks": [["000977", "0", "浪潮信息"]]},
        {"key": "memory", "name": "存储芯片", "terms": ["存储"],
         "board_names": ["存储芯片"], "board_type": "concept",
         "stocks": [["603986", "1", "兆易创新"]]}
    ]
}

def fake_close(secid, day, warnings, label):
    return {"status": "ok", "market_date": day, "change_pct": 2.0,
            "close": 100.0, "reference_close": 98.0392,
            "secid": secid, "source": "mock", "value_kind": "daily_close"}

class TestCloseReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cfg = self.root / "config/sector_watchlist.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps(TRACKS, ensure_ascii=False), encoding="utf-8")
        morning = {"report_date": DAY, "generated_at_utc": "2026-11-05T00:40:00+00:00",
                   "a_share_bias": "mixed", "a_share_sectors": [
                       {"sector": "半导体、AI服务器与存储", "bias": "positive", "reason": "前瞻"}
                   ]}
        path = data_path(self.root, "analysis", DAY)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(morning, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_freeze_only_preopen_and_immutable(self):
        time = datetime(2026, 11, 5, 8, 50, tzinfo=BJ)
        self.assertEqual(freeze_forecast(DAY, self.root, time), "frozen")
        freeze = data_path(self.root, "forecasts", DAY)
        original = freeze.read_text(encoding="utf-8")
        self.assertEqual(freeze_forecast(DAY, self.root, time), "already_frozen")
        self.assertEqual(freeze.read_text(encoding="utf-8"), original)
        self.assertEqual(freeze_forecast(DAY, self.root, datetime(2026, 11, 5, 15, 0, tzinfo=BJ)),
                         "outside_preopen_window")

    def test_no_fake_historical_freeze(self):
        self.assertEqual(freeze_forecast(DAY, self.root,
                         datetime(2026, 11, 6, 8, 15, tzinfo=BJ)), "outside_preopen_window")

    def test_multi_sector_prediction_scored_once(self):
        forecast = {"a_share_sectors": [
            {"sector": "半导体、AI服务器与存储", "bias": "positive", "reason": "前瞻"}
        ], "watchlist": TRACKS}
        matched = find_tracks(forecast)
        self.assertEqual(len(matched), 1)
        self.assertEqual({x["key"] for x in matched[0]["tracks"]},
                         {"semiconductor", "server", "memory"})
        freeze_forecast(DAY, self.root, datetime(2026, 11, 5, 8, 50, tzinfo=BJ))
        sectors = [
            {"name": "半导体", "kind": "industry", "code": "BK1", "change_pct_indicative": 2},
            {"name": "AI服务器", "kind": "concept", "code": "BK2", "change_pct_indicative": 3},
            {"name": "存储芯片", "kind": "concept", "code": "BK3", "change_pct_indicative": 4}
        ]
        with patch("scripts.close_review.list_sectors", side_effect=lambda typ, warnings: [x for x in sectors if x["kind"] == typ]), \
             patch("scripts.close_review.safe_bar", side_effect=fake_close), \
             patch("scripts.close_review.collect_news_clues", return_value=[]), \
             patch("scripts.close_review.time.sleep"):
            result = collect_close(DAY, self.root, datetime(2026, 11, 5, 15, 35, tzinfo=BJ))
        self.assertEqual(result, "collected")
        close = json.loads(data_path(self.root, "close", DAY).read_text(encoding="utf-8"))
        self.assertEqual(len(close["predicted_groups"]), 1)
        self.assertTrue(close["predicted_groups"][0]["direction_hit"])
        self.assertEqual(close["predicted_groups"][0]["aggregated_change_pct"], 2)
        self.assertEqual(collect_close(DAY, self.root,
                         datetime(2026, 11, 5, 15, 45, tzinfo=BJ)), "already_collected")

    def test_unconfigured_exact_board_keeps_single_sample(self):
        analysis_path = data_path(self.root, "analysis", DAY)
        a = json.loads(analysis_path.read_text(encoding="utf-8"))
        a["a_share_sectors"] = [{"sector": "消费电子", "bias": "positive", "reason": "新板块"}]
        analysis_path.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
        freeze_forecast(DAY, self.root, datetime(2026, 11, 5, 8, 50, tzinfo=BJ))
        sectors = [{"name": "消费电子", "kind": "industry",
                    "code": "BK10", "change_pct_indicative": 1}]
        with patch("scripts.close_review.list_sectors", side_effect=lambda typ, warnings: [s for s in sectors if s["kind"] == typ]), \
             patch("scripts.close_review.safe_bar", side_effect=fake_close), \
             patch("scripts.close_review.collect_news_clues", return_value=[]), \
             patch("scripts.close_review.time.sleep"):
            self.assertEqual(collect_close(DAY, self.root, datetime(2026, 11, 5, 15, 35, tzinfo=BJ)), "collected")
        result = json.loads(data_path(self.root, "close", DAY).read_text(encoding="utf-8"))
        self.assertEqual(len(result["predicted_groups"]), 1)
        self.assertTrue(result["predicted_groups"][0]["direction_hit"])
        self.assertEqual(result["predicted_groups"][0]["components"][0]["stocks"], [])
        self.assertTrue(any("without preselected stocks" in msg for msg in result["warnings"]))

    def test_unverifiable_news_rejected_and_html_escaped(self):
        with self.assertRaises(ValueError):
            validate_close_analysis({"summary": "s", "new_events": [
                {"title": "新闻", "source_ids": []}]})
        analysis = {"summary": "<script>alert(1)</script>", "news_sources": [],
                    "key_findings": [], "attributions": [], "new_events": [], "next_watch": []}
        validate_close_analysis(analysis)
        raw = {"report_date": DAY, "captured_at_utc": "2026-11-05T07:40:00+00:00",
               "benchmark": {"quote": {"change_pct": 0.1}},
               "predicted_groups": [], "hot_sectors": [], "warnings": []}
        output = render_close_report(raw, analysis)
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)

if __name__ == "__main__":
    unittest.main()
