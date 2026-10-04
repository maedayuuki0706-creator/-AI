import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
import yuuki_interim_report

from recover_delivery_journals import restore
import interim_report
import direct_discord_notify as base


class RecoveryTests(unittest.TestCase):
    def test_exact_artifact_rows_restore_once_preserving_existing_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'delivery_recovery').mkdir()
            row = {'day':'20261004','jcd':'23','rno':5,'all_picks':['1-2-3'],'sent_at':'2026-10-04T10:08:00+09:00'}
            manifest = {'records':[{'journal':'prediction_log.jsonl','artifact_id':123,'record':row}]}
            (root/'delivery_recovery/20261004_artifact_rows.json').write_text(json.dumps(manifest))
            existing = {'day':'20261003','all_picks':['6-5-4']}
            (root/'prediction_log.jsonl').write_text(json.dumps(existing)+'\n')
            self.assertEqual(restore('20261004',root=root),1)
            self.assertEqual(restore('20261004',root=root),0)
            self.assertEqual([json.loads(x) for x in (root/'prediction_log.jsonl').read_text().splitlines()],[existing,row])

    def test_skipped_longshot_does_not_enter_interim_performance(self):
        row = {'day':'20261004','jcd':'23','rno':5,'stream':'longshot','deadline':'10:20',
               'sent_at':'2026-10-04T10:08:00+09:00','status':'sniper_skip','picks':[{'combination':'1-2-3'}]}
        journal = {**row,'status':'sent','sent_at':'2026-10-04T10:30:00+09:00','payout_per_100':20000}
        counts = interim_report.tally(datetime(2026,10,4,13,tzinfo=base.JST),[journal],[],[row])
        self.assertEqual(counts,{})

    def test_delayed_yuuki_schedule_uses_due_report_slots_not_wall_clock_hour(self):
        with patch.object(yuuki_interim_report, 'send', return_value={}) as send:
            yuuki_interim_report.send_due(datetime(2026,10,4,14,35,tzinfo=base.JST))
            send.assert_called_once_with('20261004',13)
            send.reset_mock()
            self.assertEqual(yuuki_interim_report.send_due(datetime(2026,10,4,7,tzinfo=base.JST)), [])
            send.assert_not_called()


if __name__ == '__main__': unittest.main()
