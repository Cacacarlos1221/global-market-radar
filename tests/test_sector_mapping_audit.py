"""Mapping backlog is factual and approvals affect only future freezes."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from scripts.close_review import BJ, approved_watchlist, freeze_forecast, data_path
from scripts.sector_mapping_audit import audit, issues_for

class SectorMappingAuditTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        p = self.root / "config/sector_watchlist.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"schema_version": "1.0", "tracks": []}))
    def tearDown(self):
        self.dir.cleanup()
    def registry(self, **values):
        d = {"schema_version": "1.0", "approved": [], "proposals": []}
        d.update(values)
        p = self.root / "config/sector_index_registry.json"
        p.write_text(json.dumps(d, ensure_ascii=False))
    def snapshot(self, day):
        p = data_path(self.root, "close", day)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"report_date": day, "predicted_groups": [
            {"sector": "贵金属", "bias": "positive", "components": []},
            {"sector": "出口制造", "bias": "mixed", "components": [
                {"name": "出口制造", "board_type": "none", "board_code": None}]}
        ]}, ensure_ascii=False))
    def test_repeat_gap_counts_only_verified_close_days(self):
        self.registry(proposals=[{"topic": "贵金属", "priority": "high",
                                  "status": "pending_user_confirmation", "candidates": []}])
        self.snapshot("2026-11-04")
        self.snapshot("2026-11-05")
        result = audit("2026-11-05", self.root)
        metal = next(x for x in result["pending"] if x["topic"] == "贵金属")
        self.assertEqual(metal["observed_days"], 2)
        self.assertEqual(metal["observed_dates"], ["2026-11-04", "2026-11-05"])
        self.assertIn("晨报主题没有固定跟踪指数", metal["gap_reasons"])
        self.assertTrue(result["latest_close_snapshot_present"])
        self.assertEqual(next(x for x in result["pending"] if x["topic"] == "出口制造")
                         ["observed_days"], 2)
    def test_known_code_missing_price_is_not_mapping_gap(self):
        group = {"sector": "半导体", "components": [
            {"name": "半导体", "board_code": "BK1036", "board_type": "industry",
             "board_name": "半导体", "quote": {"status": "unavailable"}}]}
        self.assertEqual(issues_for(group), [])
        group["components"][0]["is_proxy"] = True
        self.assertEqual(issues_for(group), [("半导体", "proxy_requires_definition")])
    def test_confirmed_mapping_is_future_only(self):
        decision = {"topic": "贵金属", "status": "approved",
                    "approved_at_utc": "2026-11-05T08:35:00+00:00",
                    "effective_from": "2026-11-06",
                    "track": {"key": "precious_metals", "name": "贵金属",
                              "terms": ["贵金属"], "board_names": ["贵金属"],
                              "board_type": "industry", "stocks": []}}
        self.registry(approved=[decision])
        nov5 = datetime(2026, 11, 5, 16, 45, tzinfo=BJ)
        nov6 = datetime(2026, 11, 6, 8, 25, tzinfo=BJ)
        early, approvals, sha = approved_watchlist(self.root, "2026-11-05", nov5)
        self.assertEqual(early["tracks"], [])
        self.assertEqual(approvals, [])
        future, approvals, sha = approved_watchlist(self.root, "2026-11-06", nov6)
        self.assertEqual(future["tracks"][0]["key"], "precious_metals")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(sha), 64)
        self.snapshot("2026-11-05")
        self.assertFalse(any(x["topic"] == "贵金属" for x in audit("2026-11-06", self.root)["pending"]))
    def test_frozen_watchlist_records_approval_provenance(self):
        self.registry(approved=[{"topic": "贵金属", "status": "approved",
            "approved_at_utc": "2026-11-05T08:35:00+00:00",
            "effective_from": "2026-11-06",
            "track": {"key": "precious_metals", "name": "贵金属",
                      "terms": ["贵金属"], "board_names": ["贵金属"],
                      "board_type": "industry", "stocks": []}}])
        p = data_path(self.root, "analysis", "2026-11-06")
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"report_date": "2026-11-06",
            "generated_at_utc": "2026-11-06T00:05:00+00:00",
            "a_share_sectors": [{"sector": "贵金属", "bias": "positive", "reason": "盘前利好"}]}))
        self.assertEqual(freeze_forecast("2026-11-06", self.root,
                         datetime(2026, 11, 6, 8, 25, tzinfo=BJ)), "frozen")
        frozen = json.loads(data_path(self.root, "forecasts", "2026-11-06").read_text())
        self.assertEqual(frozen["sector_mapping_approvals_applied"][0]["topic"], "贵金属")
        self.assertEqual(frozen["watchlist"]["tracks"][0]["board_names"], ["贵金属"])

if __name__ == "__main__":
    unittest.main()
