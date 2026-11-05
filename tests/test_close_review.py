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
         "board_names": ["AI服务器", "服务器", "液冷服务器"], "board_type": "concept",
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

    def test_collect_cli_fails_when_no_same_day_market_data(self):
        from scripts.close_review import main
        with patch("sys.argv", ["close_review", "--collect-only", "--date", DAY]), \
             patch("scripts.close_review.collect_close",
                   return_value="no_same_day_close_data: public market API unavailable"):
            with self.assertRaises(SystemExit) as raised:
                main()
            self.assertEqual(raised.exception.code, 1)

    def test_collect_cli_skips_valid_early_window_without_false_error(self):
        from scripts.close_review import main
        with patch("sys.argv", ["close_review", "--collect-only", "--date", DAY]), \
             patch("scripts.close_review.collect_close", return_value="not_collection_window"):
            main()

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

    def test_no_freeze_still_collects_morning_sector_but_never_scores(self):
        boards = [
            {"name": "半导体", "kind": "industry", "code": "BK1", "change_pct_indicative": 2},
            {"name": "AI服务器", "kind": "concept", "code": "BK2", "change_pct_indicative": 3},
            {"name": "存储芯片", "kind": "concept", "code": "BK3", "change_pct_indicative": 4}
        ]
        with patch("scripts.close_review.list_sectors", side_effect=lambda kind, warnings: [
            x for x in boards if x["kind"] == kind]), \
             patch("scripts.close_review.safe_bar", side_effect=fake_close), \
             patch("scripts.close_review.collect_news_clues", return_value=[]), \
             patch("scripts.close_review.time.sleep"):
            status = collect_close(DAY, self.root, datetime(2026, 11, 5, 15, 35, tzinfo=BJ))
        self.assertEqual(status, "collected")
        data = json.loads(data_path(self.root, "close", DAY).read_text(encoding="utf-8"))
        self.assertIsNone(data["forecast_sha256"])
        self.assertEqual(data["forecast_status"], "morning_analysis_unfrozen")
        self.assertEqual(len(data["predicted_groups"]), 1)
        self.assertEqual(len(data["predicted_groups"][0]["components"]), 3)
        self.assertEqual(data["predicted_groups"][0]["aggregated_change_pct"], 2.0)
        self.assertIsNone(data["predicted_groups"][0]["direction_hit"])
        self.assertEqual(data["predicted_groups"][0]["evaluation"], "unfrozen_observation")

    def test_without_morning_analysis_uses_preconfigured_observation_pool(self):
        data_path(self.root, "analysis", DAY).unlink()
        with patch("scripts.close_review.list_sectors", return_value=[]), \
             patch("scripts.close_review.safe_bar", side_effect=fake_close), \
             patch("scripts.close_review.collect_news_clues", return_value=[]), \
             patch("scripts.close_review.time.sleep"):
            self.assertEqual(collect_close(DAY, self.root,
                             datetime(2026, 11, 5, 15, 35, tzinfo=BJ)), "collected")
        result = json.loads(data_path(self.root, "close", DAY).read_text(encoding="utf-8"))
        self.assertEqual(result["forecast_status"], "watchlist_only")
        self.assertEqual(len(result["predicted_groups"]), 3)
        self.assertTrue(all(g["direction_hit"] is None for g in result["predicted_groups"]))

    def test_no_benchmark_still_keeps_same_day_sector_and_stock(self):
        with patch("scripts.close_review.list_sectors",
                   side_effect=lambda kind, warnings: [{"name": "半导体", "kind": "industry",
                   "code": "BK1", "change_pct_indicative": 2}] if kind == "industry" else []), \
             patch("scripts.close_review.safe_bar", side_effect=lambda secid, day, warnings, label:
                   {"status": "unavailable", "change_pct": None, "market_date": None}
                   if secid == "1.000300" else fake_close(secid, day, warnings, label)), \
             patch("scripts.close_review.yahoo_benchmark_fallback",
                   return_value={"status": "unavailable", "change_pct": None, "market_date": None}), \
             patch("scripts.close_review.collect_news_clues", return_value=[]), \
             patch("scripts.close_review.time.sleep"):
            self.assertEqual(collect_close(DAY, self.root,
                             datetime(2026, 11, 5, 15, 35, tzinfo=BJ)), "collected")
        result = json.loads(data_path(self.root, "close", DAY).read_text(encoding="utf-8"))
        self.assertIsNone(result["predicted_groups"][0]["excess_vs_csi300_pct"])
        self.assertGreater(result["observed_close_instruments"], 0)

    def test_individual_sector_excess_without_composite_index(self):
        analysis = {"summary": "观察性研究", "news_sources": [], "key_findings": [],
                    "attributions": [], "new_events": [], "next_watch": []}
        raw = {"report_date": DAY, "captured_at_utc": "2026-11-05T07:40:00+00:00",
               "forecast_sha256": None, "forecast_status": "morning_analysis_unfrozen",
               "benchmark": {"quote": {"status": "ok", "change_pct": 2.3066,
                                        "market_date": DAY}},
               "predicted_groups": [{
                   "sector": "半导体、AI服务器与存储", "bias": "positive",
                   "reason": "晨报方向", "aggregated_change_pct": None,
                   "excess_vs_csi300_pct": None, "direction_hit": None,
                   "evaluation": "unfrozen_observation", "components": [
                       {"name": "半导体", "board_name": "半导体", "board_code": "BK1",
                        "is_proxy": False, "quote": {"status": "ok", "change_pct": 10.6424,
                                                   "market_date": DAY}, "stocks": []},
                       {"name": "AI服务器", "board_name": "液冷服务器", "board_code": "BK2",
                        "is_proxy": True, "quote": {"status": "ok", "change_pct": 5.3407,
                                                  "market_date": DAY}, "stocks": []}
                   ]
               }], "hot_sectors": [], "news_clues": [], "warnings": []}
        page = render_close_report(raw, analysis)
        self.assertIn("03 / GMR 盘后复盘与新闻归因", page)
        self.assertIn("GMR · 盘后综合判断", page)
        self.assertIn("不展示虚构的综合涨跌", page)
        self.assertIn("+8.34 个百分点", page)
        self.assertIn("+3.03 个百分点", page)
        self.assertIn("代理主题（仅用于观察，不参与命中率）", page)
        self.assertNotIn("03 / GPT", page)

    def test_board_list_502_can_be_recovered_without_overwriting_raw(self):
        from scripts.close_review import enrich_close, effective_close
        yesterday = data_path(self.root, "close", "2026-11-04")
        yesterday.parent.mkdir(parents=True, exist_ok=True)
        yesterday.write_text(json.dumps({
            "report_date": "2026-11-04",
            "predicted_groups": [{"components": [
                {"board_type": "industry", "board_name": "半导体", "board_code": "BK1"},
                {"board_type": "concept", "board_name": "液冷服务器", "board_code": "BK2"}]}],
            "hot_sectors": []
        }, ensure_ascii=False), encoding="utf-8")
        freeze_forecast(DAY, self.root, datetime(2026, 11, 5, 8, 50, tzinfo=BJ))
        base = data_path(self.root, "close", DAY)
        base.write_text(json.dumps({
            "report_date": DAY, "forecast_sha256": "frozen", "warnings": [
                "concept board list page 1: HTTP 502"],
            "benchmark": {"quote": {"status": "ok", "market_date": DAY, "change_pct": 1.0}},
            "predicted_groups": [
                {"sector": "半导体", "bias": "positive", "components": [
                    {"key": "semiconductor", "name": "半导体", "board_type": "industry",
                     "board_code": None, "board_name": None, "is_proxy": False,
                     "quote": {"status": "unavailable"}}]},
                {"sector": "AI服务器", "bias": "positive", "components": [
                    {"key": "server", "name": "AI服务器", "board_type": "concept",
                     "board_code": None, "board_name": None, "is_proxy": False,
                     "quote": {"status": "unavailable"}}]}
            ], "hot_sectors": []
        }, ensure_ascii=False), encoding="utf-8")
        unchanged = base.read_bytes()
        with patch("scripts.close_review.safe_bar", return_value={
            "status": "ok", "market_date": DAY, "change_pct": 4.0,
            "close": 104.0, "reference_close": 100.0
        }):
            result = enrich_close(DAY, self.root)
        self.assertIn("半导体", result)
        self.assertEqual(base.read_bytes(), unchanged)
        corrected = effective_close(self.root, DAY)
        self.assertEqual(corrected["original_close_sha256"], __import__("hashlib").sha256(unchanged).hexdigest())
        self.assertEqual(corrected["predicted_groups"][0]["components"][0]["board_code"], "BK1")
        self.assertTrue(corrected["predicted_groups"][0]["direction_hit"])
        self.assertEqual(corrected["predicted_groups"][0]["excess_vs_csi300_pct"], 3.0)
        self.assertEqual(corrected["predicted_groups"][1]["components"][0]["board_name"], "液冷服务器")
        self.assertTrue(corrected["predicted_groups"][1]["components"][0]["is_proxy"])
        self.assertIsNone(corrected["predicted_groups"][1]["direction_hit"])
        self.assertEqual(enrich_close(DAY, self.root), "revision_already_exists")

    def test_recovery_rejects_old_date_quotes_and_keeps_snapshot_unchanged(self):
        from scripts.close_review import enrich_close
        prev = data_path(self.root, "close", "2026-11-04")
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_text(json.dumps({"predicted_groups": [{"components": [
            {"board_type": "industry", "board_name": "半导体", "board_code": "BK1"}]}]}))
        freeze_forecast(DAY, self.root, datetime(2026, 11, 5, 8, 50, tzinfo=BJ))
        current = data_path(self.root, "close", DAY)
        current.write_text(json.dumps({"report_date": DAY, "warnings": [],
            "benchmark": {"quote": {"status": "ok", "market_date": DAY, "change_pct": 1.0}},
            "forecast_sha256": "frozen", "predicted_groups": [
                {"sector": "半导体", "bias": "positive", "components": [{
                    "key": "semiconductor", "name": "半导体", "quote": {"status": "unavailable"}
                }]}
            ], "hot_sectors": []}))
        with patch("scripts.close_review.safe_bar", return_value={
            "status": "unavailable", "market_date": "2026-11-04", "change_pct": None
        }):
            self.assertEqual(enrich_close(DAY, self.root), "no_verified_same_day_board_quotes")
        self.assertFalse(data_path(self.root, "close_revisions", DAY).exists())

    def test_board_list_502_uses_alternate_host_with_public_token(self):
        from scripts.close_review import json_api
        payload = {"data": {"total": 1, "diff": [
            {"f12": "BK1036", "f14": "半导体", "f3": 2.8}
        ]}}
        called = []
        def fake_api(url, timeout):
            called.append(url)
            if len(called) == 1:
                raise OSError("HTTP Error 502: Bad Gateway")
            return json.dumps(payload).encode("utf-8")
        with patch("scripts.close_review.read_url", side_effect=fake_api), \
             patch("scripts.close_review.time.sleep"):
            data = json_api("clist/get", {"pn": 1, "fs": "m:90+t:2+f:!50",
                                         "fields": "f12,f14,f3"})
        self.assertEqual(data["diff"][0]["f12"], "BK1036")
        self.assertEqual(len(called), 2)
        self.assertIn("push2delay.eastmoney.com", called[1])
        self.assertIn("ut=bd1d9ddb04089700cf9c27f6f7426281", called[1])

    def test_partial_live_ranking_keeps_historically_confirmed_fixed_boards(self):
        yesterday = data_path(self.root, "close", "2026-11-04")
        yesterday.parent.mkdir(parents=True, exist_ok=True)
        yesterday.write_text(json.dumps({"report_date": "2026-11-04", "predicted_groups": [{
            "components": [
                {"board_type": "concept", "board_name": "存储芯片", "board_code": "BK3"},
                {"board_type": "concept", "board_name": "液冷服务器", "board_code": "BK2"}
            ]}], "hot_sectors": []}, ensure_ascii=False), encoding="utf-8")
        live = [{"name": "半导体", "kind": "industry", "code": "BK1",
                 "change_pct_indicative": 2.0}]
        with patch("scripts.close_review.list_sectors",
                   side_effect=lambda kind, warnings: live if kind == "industry" else []), \
             patch("scripts.close_review.safe_bar", side_effect=fake_close), \
             patch("scripts.close_review.collect_news_clues", return_value=[]), \
             patch("scripts.close_review.time.sleep"):
            self.assertEqual(collect_close(DAY, self.root,
                             datetime(2026, 11, 5, 15, 35, tzinfo=BJ)), "collected")
        raw = json.loads(data_path(self.root, "close", DAY).read_text(encoding="utf-8"))
        group = raw["predicted_groups"][0]
        self.assertEqual(len(group["components"]), 3)
        self.assertEqual({x["board_code"] for x in group["components"]},
                         {"BK1", "BK2", "BK3"})
        self.assertTrue(next(x for x in group["components"]
                             if x["name"] == "AI服务器")["is_proxy"])
        self.assertIsNone(group["direction_hit"])

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
