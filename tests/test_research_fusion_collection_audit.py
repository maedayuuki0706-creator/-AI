import json
from pathlib import Path
import tempfile
import unittest

from research_fusion_collection_audit import audit
from research_fusion_roi_replay import when


class HealthTests(unittest.TestCase):
    def test_completed_run_with_timeouts_is_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/"heartbeat.json").write_text(json.dumps({"status": "completed",
                "finished_at": "2026-10-15T19:28:00+09:00",
                "captures": [{"status": "budget_exceeded"}]}))
            r = audit(root, when("2026-10-15T19:30:00+09:00"))
            self.assertEqual(r["health"], "DEGRADED")
            self.assertIn("capture_failures_or_deferrals", r["reasons"])

    def test_stale_heartbeat_does_not_report_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/"heartbeat.json").write_text(json.dumps({"status": "completed",
                "finished_at": "2026-10-15T19:28:00+09:00", "captures": []}))
            r = audit(root, when("2026-10-15T23:00:00+09:00"))
            self.assertIn("heartbeat_older_than_20_minutes", r["reasons"])

    def test_no_heartbeat_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(audit(Path(d), when("2026-10-15T23:00:00+09:00"))["health"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
