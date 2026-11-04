"""Static contract checks: no future edit can quietly remove the morning fallbacks."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class MorningWorkflowContractTests(unittest.TestCase):
    def test_daily_uses_early_collection_and_recovery_windows(self):
        s = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
        for cron in ("5 0 * * *", "15 0 * * *", "35 0 * * *", "5 1 * * *"):
            self.assertIn("cron: '" + cron + "'", s)
        for trigger in ("data/analysis/**", "data/requests/**"):
            self.assertIn(trigger, s)

    def test_freeze_analysis_and_release_checks_are_paired(self):
        s = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
        self.assertIn("python -m scripts.close_review --freeze-only", s)
        self.assertIn("python -m scripts.pipeline --collect-only", s)
        self.assertIn("python -m scripts.backfill_missing --date", s)
        self.assertIn("python -m scripts.pipeline --render-only", s)
        self.assertLess(s.index("python -m scripts.backfill_missing --date"),
                        s.index("python -m scripts.pipeline --render-only"))
        self.assertIn("python -m scripts.release_check --date", s)
        self.assertIn("python -m scripts.morning_audit --date", s)
        self.assertLess(s.index("python -m scripts.close_review --freeze-only"),
                        s.index("python -m scripts.release_check --date"))

    def test_source_pipeline_never_claims_auto_ai_analysis(self):
        s = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")
        self.assertIn("if out.exists():", s)
        self.assertIn("raise FileExistsError(", s)

if __name__ == "__main__":
    unittest.main()
