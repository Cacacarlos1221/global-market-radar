"""Offline smoke tests for the opt-in experimental Stage-2 harness."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from agent.orchestrator import build_analysis, plan, publish_reviewed, write_preview
from agent.flow import run_flow

DATE = "2026-11-04"
NOW = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)

class StubClient:
    def __init__(self, source_ids=None):
        self.source_ids = source_ids or []
    def generate_json(self, system_prompt, user_prompt):
        if "AGENT_CRITIC_V1" in system_prompt:
            return {"approved": True, "findings": []}
        return {
            "market_summary": "报价仅来自冻结测试快照；未证明新闻对价格有因果作用。",
            "a_share_bias": "watch", "a_share_outlook": "仅作条件性观察。",
            "a_share_sectors": [], "risks": ["证据不充分"], "uncertainty": "high",
            "news_digest": {"overview": "核验来源简述" if self.source_ids else "",
                            "items": ([{"title": "来源事件", "summary": "人工审阅内容",
                                       "market_impact": "仍需验证市场影响",
                                       "importance": "medium", "source_ids": self.source_ids}]
                                      if self.source_ids else [])},
        }

class AgentFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        target = self.root / "data/daily/2026/11/2026-11-04.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({
            "report_date": DATE, "collected_at_utc": "2026-11-04T00:15:00Z",
            "quotes": [], "news": [{"headline": "Unverified headline"}]}), encoding="utf-8")
    def tearDown(self):
        self.temp.cleanup()
    def evidence(self):
        p = self.root / "evidence.json"
        p.write_text(json.dumps({"report_date": DATE, "news_sources": [{
            "id": "S1", "title": "Human-read article", "publisher": "Publisher",
            "url": "https://example.com/article", "verification": "reported",
            "fact_notes": "The test reviewer read this source.",
            "reviewed_at_utc": "2026-11-04T00:25:00Z", "published_at_utc": None
        }]}), encoding="utf-8")
        return p
    def test_plan_is_read_only(self):
        result = plan(self.root, DATE, now_utc=NOW)
        self.assertEqual(result["unverified_rss_leads"], 1)
        self.assertFalse((self.root / "agent/output").exists())
    def test_unverified_rss_never_becomes_digest(self):
        doc = build_analysis(self.root, DATE, StubClient(), now_utc=NOW)
        self.assertEqual(doc["news_digest"]["items"], [])
        self.assertEqual(doc["news_sources"], [])
    def test_valid_manual_evidence_and_explicit_publish(self):
        evidence = self.evidence()
        result = run_flow(self.root, DATE, StubClient(["S1"]), evidence, now_utc=NOW)
        self.assertEqual(result["status"], "passed_pending_human_approval")
        with self.assertRaises(PermissionError):
            publish_reviewed(self.root, DATE, evidence)
        target = publish_reviewed(self.root, DATE, evidence, reviewed=True)
        self.assertTrue(target.exists())
        with self.assertRaises(FileExistsError):
            publish_reviewed(self.root, DATE, evidence, reviewed=True)
    def test_unknown_source_id_fails_closed(self):
        with self.assertRaises(ValueError):
            build_analysis(self.root, DATE, StubClient(["invented"]), self.evidence(), now_utc=NOW)
    def test_no_source_cannot_claim_verified_news(self):
        with self.assertRaises(ValueError):
            build_analysis(self.root, DATE, StubClient(["S1"]), now_utc=NOW)

if __name__ == "__main__":
    unittest.main()
