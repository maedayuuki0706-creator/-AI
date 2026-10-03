from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import hit_alerts as alerts
import hit_alerts_fast as fast
import sokuhou_delivery as delivery
from tests.test_sokuhou_delivery import MemoryStore


class FastHitAlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name)/'hits.jsonl'
        self.row = {'day':'20261003','jcd':'24','rno':10,'venue':'大村',
                    'deadline':'18:00','sent_at':'2026-10-03T17:50:00+09:00','main':['1-2-3']}
        self.sender = Mock(return_value={'id':'111'})
        self.store = MemoryStore()
        patches = [patch.object(alerts, 'DELIVERY_PATH', self.journal),
                   patch.object(delivery, 'print', create=True),
                   patch.object(fast, 'print', create=True),
                   patch.object(fast, '_normal_candidates', return_value=[('normal', self.row)]),
                   patch.object(fast, '_opportunity_candidates', return_value=[]),
                   patch.object(alerts, '_load_official', return_value={'status':'settled','payouts':{'1-2-3':1200}}),
                   patch.object(alerts, '_message', return_value='大村 10R 的中'),
                   patch.object(alerts, '_send_hit_channel', self.sender),
                   patch.object(delivery, 'STORE', self.store),
                   patch.object(delivery, 'policy', return_value={'enabled':True,'resume_after':'2026-10-03T17:30:00+09:00'})]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.now = datetime(2026, 10, 3, 19, tzinfo=alerts.base.JST)

    def run_pass(self):
        return fast.check_and_send('20261003', self.now)

    def test_lost_local_journal_recovers_receipt_without_second_post(self):
        self.assertEqual(self.run_pass(), 1)
        self.journal.unlink()
        self.assertEqual(self.run_pass(), 1)
        self.sender.assert_called_once()
        row = json.loads(self.journal.read_text())
        self.assertEqual(row['message_id'], '111')
        self.assertEqual(row['status'], 'sent')

    def test_paused_does_no_result_lookup_or_send(self):
        with patch.object(delivery, 'paused', return_value=True):
            self.assertEqual(self.run_pass(), 0)
        alerts._load_official.assert_not_called()
        self.sender.assert_not_called()

    def test_old_hit_is_counted_but_never_replayed(self):
        self.row['deadline'] = '17:00'
        self.assertEqual(self.run_pass(), 0)
        self.sender.assert_not_called()
        self.assertEqual(json.loads(self.journal.read_text())['status'], 'suppressed')
        self.assertEqual(alerts._venue_hit_count('20261003', '大村', 'normal'), 1)
        from interim_report import tally
        result = tally(self.now, [json.loads(self.journal.read_text())])
        self.assertEqual(result['24']['normal']['hits'], 1)

    def test_timeout_does_not_create_fake_sent_receipt(self):
        self.sender.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError):
            self.run_pass()
        with self.assertRaises(RuntimeError):
            self.run_pass()
        self.sender.assert_called_once()
        self.assertFalse(self.journal.exists())

    def test_result_wait_is_not_a_miss(self):
        alerts._load_official.return_value = None
        self.assertEqual(self.run_pass(), 0)
        self.assertFalse(self.journal.exists())
        self.sender.assert_not_called()

    def test_confirmed_miss_is_settled_without_notification(self):
        alerts._load_official.return_value = {'status':'settled','payouts':{'2-1-3':1200}}
        self.assertEqual(self.run_pass(), 0)
        self.assertEqual(self.run_pass(), 0)
        self.sender.assert_not_called()
        self.assertEqual(len(self.journal.read_text().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
