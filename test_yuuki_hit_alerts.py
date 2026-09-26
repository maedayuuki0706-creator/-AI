import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yuuki_hit_alerts as alerts


class YuukiHitAlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.p3 = root / "delivery"
        self.scores = root / "scoreboard"
        self.patches = [
            patch.object(alerts, "P3_ROOT", self.p3),
            patch.object(alerts, "SCORE_ROOT", self.scores),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def race(self, rno, *, hit=True, status="settled", delivered=True, selected=False):
        key = f"20260927_08_{rno:02d}"
        row = {
            "key": key, "day": "20260927", "venue": "常滑", "rno": rno,
            "official": {"status": status, "payouts": {"1-2-3": 12800}},
            "prediction_digests": {"prototype3": "digest"},
            "models": {"prototype3": {
                "hit": hit, "winning_picks": ["1-2-3"] if hit else [],
                "main_hit": True, "point_count": 10,
            }},
        }
        self.put(self.scores / "20260927" / "results" / f"{key}.json", row)
        if delivered:
            self.put(self.p3 / "deliveries" / f"{key}.json", {
                "key": key, "prediction_digest": "digest",
            })
        if selected:
            self.put(self.p3 / "selected_deliveries" / f"{key}.json", {"key": key})
        return key

    def test_only_delivered_settled_hits_and_once(self):
        key = self.race(1, selected=True)
        self.race(2, hit=False)
        self.race(3, status="pending")
        self.race(4, delivered=False)
        sent = []
        self.assertEqual(alerts.run("20260927", sender=sent.append), 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("新人予想家ゆうきが持ってきた", sent[0])
        self.assertIn("厳選予想も的中", sent[0])
        self.assertIn("12,800円", sent[0])
        self.assertTrue((self.p3 / "hit_alerts" / f"{key}.json").exists())
        self.assertEqual(alerts.run("20260927", sender=sent.append), 0)

    def test_failure_retries_without_receipt(self):
        key = self.race(5)

        def failed(_):
            raise OSError("temporary")

        self.assertEqual(alerts.run("20260927", sender=failed), 0)
        self.assertFalse((self.p3 / "hit_alerts" / f"{key}.json").exists())
        sent = []
        self.assertEqual(alerts.run("20260927", sender=sent.append), 1)
        self.assertNotIn("厳選予想も的中", sent[0])
        self.assertEqual(alerts.run("20260926", sender=sent.append), 0)


if __name__ == "__main__":
    unittest.main()
