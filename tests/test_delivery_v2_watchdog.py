import tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from delivery_v2 import receipts
from delivery_v2.watchdog import Expected, missing

class WatchdogTest(unittest.TestCase):
    def test_only_reports_unconfirmed_after_grace(self):
        now=datetime(2026,10,4,4,0,tzinfo=timezone.utc)
        rows=[Expected("main","20261004","01",1,"2026-10-04T03:58:00+00:00"),Expected("main","20261004","01",2,"2026-10-04T04:00:00+00:00")]
        with tempfile.TemporaryDirectory() as td:
            with patch.object(receipts,"ROOT",Path(td)):
                self.assertEqual([x["rno"] for x in missing(rows,now=now,grace_seconds=90)],[1])
                receipts.write_confirmed("main","20261004","01",1,"123456")
                self.assertEqual(missing(rows,now=now,grace_seconds=90),[])

if __name__=="__main__": unittest.main()
