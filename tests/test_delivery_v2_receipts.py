import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from delivery_v2 import receipts, guard
from delivery_v2.guard import deliver_once
from delivery_v2.store import FileStore

class ReceiptTest(unittest.TestCase):
    def test_deliver_once_deduplicates_confirmed_message(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(receipts,"ROOT",Path(td)/'receipts'), patch.object(guard,"RECOVERY",Path(td)/'recovery'):
                calls=[]
                def sender(content):
                    calls.append(content); return "987654321"
                a=deliver_once("main","20261004","01",3,"hello",sender,store=FileStore())
                b=deliver_once("main","20261004","01",3,"hello",sender,store=FileStore())
                self.assertEqual(a["status"],"sent")
                self.assertEqual(b["status"],"already_sent")
                self.assertEqual(len(calls),1)

if __name__=="__main__": unittest.main()
