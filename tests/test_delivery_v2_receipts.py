import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from delivery_v2 import receipts
from delivery_v2.guard import deliver_once

class ReceiptTest(unittest.TestCase):
    def test_deliver_once_deduplicates_confirmed_message(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(receipts,"ROOT",Path(td)):
                calls=[]
                def sender(content):
                    calls.append(content); return "987654321"
                a=deliver_once("main","20261004","01",3,"hello",sender)
                b=deliver_once("main","20261004","01",3,"hello",sender)
                self.assertEqual(a["status"],"sent")
                self.assertEqual(b["status"],"already_sent")
                self.assertEqual(len(calls),1)

if __name__=="__main__": unittest.main()
