"""End-to-end offline workflow tests; no API key and no network needed."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from agent.flow import run_flow
from agent.orchestrator import plan, publish_reviewed
from agent.tools.io import load_effective_snapshot

DAY = "2026-11-04"
AS_OF = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)

class FakeModel:
    def __init__(self, approve=True):
        self.calls = 0
        self.approve = approve
    def generate_json(self, system_prompt, user_prompt):
        self.calls += 1
        if "AGENT_CRITIC_V1" in system_prompt:
            return {"approved": self.approve,
                    "findings": [] if self.approve else ["Unsupported asserted causality"]}
        return {
            "market_summary": "当前只有有限的行情信息，无法证明驱动原因。",
            "a_share_bias": "watch", "a_share_outlook": "关注可能风险，勿将推断当作事实。",
            "a_share_sectors": [], "risks": ["来源不足"], "uncertainty": "high",
            "news_digest": {"overview": "", "items": []},
        }

class AgentFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        target = self.root / "data/daily/2026/11/2026-11-04.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"report_date": DAY,
            "collected_at_utc": "2026-11-04T00:15:00Z",
            "quotes": [{"key": "AUD_CNY", "status": "unavailable", "label": "AUD/CNY",
                        "value": None, "market_date": None, "observed_at_utc": None,
                        "change_pct": None, "error": "No quote"}],
            "news": [
                {"event_id": "A", "headline": "Candidate A", "published_at_utc": "2026-11-04T00:20:00Z"},
                {"event_id": "A2", "headline": "Candidate A", "published_at_utc": "2026-11-04T00:21:00Z"},
                {"event_id": "B", "headline": "Future B", "published_at_utc": "2026-11-04T10:20:00Z"},
            ]}), encoding="utf-8")
    def tearDown(self):
        self.tmp.cleanup()
    def add_supplement(self, collected):
        folder = self.root / "data/supplements/2026/11/2026-11-04"
        folder.mkdir(parents=True)
        (folder / "USD_CNY.json").write_text(json.dumps({
            "report_date": DAY, "collected_at_utc": collected,
            "quote": {"key": "USD_CNY", "label": "USD/CNY", "status": "ok",
                      "value": 7.2, "market_date": DAY,
                      "value_kind": "intraday_observation", "change_pct": 0.1}
        }), encoding="utf-8")
    def test_research_queue_and_pending_html(self):
        out = run_flow(self.root, DAY, now_utc=AS_OF)
        self.assertEqual(out["status"], "needs_model_and_reviewed_evidence")
        self.assertTrue(Path(out["html"]).exists())
        queue = json.loads(Path(out["research_queue"]).read_text())
        self.assertEqual(len(queue["candidates"]), 1)
        self.assertEqual(queue["candidates"][0]["review_status"], "unverified_rss_lead")
        self.assertFalse((self.root / "agent/output/2026-11-04.analysis.json").exists())
    def test_model_analyst_and_critic_two_pass(self):
        fake = FakeModel()
        out = run_flow(self.root, DAY, client=fake, now_utc=AS_OF)
        self.assertEqual(fake.calls, 2)
        self.assertEqual(out["status"], "passed_pending_human_approval")
        audit = json.loads((self.root / "agent/output/2026-11-04/audit.json").read_text())
        self.assertEqual(audit["status"], "passed_pending_human_approval")
        self.assertIn("preview_sha256", audit["steps"][-1])
        preview = json.loads(Path(out["analysis_preview"]).read_text())
        self.assertEqual(preview["news_digest"]["items"], [])
        self.assertTrue(preview["agent_meta"]["snapshot_sha256"])
        with self.assertRaises(PermissionError):
            publish_reviewed(self.root, DAY)
        target = publish_reviewed(self.root, DAY, reviewed=True)
        self.assertTrue(target.exists())
    def test_rejected_critic_blocks_preview(self):
        model = FakeModel(approve=False)
        with self.assertRaises(ValueError):
            run_flow(self.root, DAY, client=model, now_utc=AS_OF)
        audit = json.loads((self.root / "agent/output/2026-11-04/audit.json").read_text())
        self.assertEqual(audit["status"], "blocked")
        self.assertFalse((self.root / "agent/output/2026-11-04.analysis.json").exists())
    def test_cutoff_excludes_future_supplement(self):
        self.add_supplement("2026-11-04T09:00:00Z")
        snapshot, _, included, excluded = load_effective_snapshot(self.root, DAY, AS_OF)
        self.assertEqual([x["key"] for x in snapshot["quotes"]], ["AUD_CNY"])
        self.assertEqual(len(included), 0)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(plan(self.root, DAY, now_utc=AS_OF)["excluded_future_supplements"], 1)
    def test_valid_supplement_included_with_provenance(self):
        self.add_supplement("2026-11-04T00:35:00Z")
        snapshot, _, included, excluded = load_effective_snapshot(self.root, DAY, AS_OF)
        self.assertEqual(snapshot["quotes"][0]["key"], "USD_CNY")
        self.assertEqual(snapshot["quotes"][0]["supplement_collected_at_utc"], "2026-11-04T00:35:00Z")
        self.assertEqual(len(included), 1)
        self.assertEqual(excluded, [])
    def test_publishing_modified_preview_is_rejected(self):
        out = run_flow(self.root, DAY, FakeModel(), now_utc=AS_OF)
        Path(out["analysis_preview"]).write_text(Path(out["analysis_preview"]).read_text() + "\n")
        with self.assertRaises(PermissionError):
            publish_reviewed(self.root, DAY, reviewed=True)
    def test_input_snapshot_future_is_rejected(self):
        with self.assertRaises(ValueError):
            run_flow(self.root, DAY, now_utc=datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc))
        audit = json.loads((self.root / "agent/output/2026-11-04/audit.json").read_text())
        self.assertEqual(audit["status"], "blocked")

if __name__ == "__main__":
    unittest.main()
