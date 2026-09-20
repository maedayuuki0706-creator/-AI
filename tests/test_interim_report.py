from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import interim_report as report


def at(hour, minute=0, day=21):
    return datetime(2026, 9, day, hour, minute, tzinfo=report.base.JST)


def record(rno, status, hour=12, *, stream='normal', jcd='24', minute=0):
    return {'day': '20260921', 'jcd': jcd, 'rno': rno, 'stream': stream,
            'status': status, 'sent_at': at(hour, minute).isoformat()}


class InterimReportTests(unittest.TestCase):
    def test_cutoff_deduplication_and_three_independent_streams(self):
        hit = record(1, 'sent')
        rows = [hit, hit.copy(), record(2, 'miss'), record(3, 'sent', 13, minute=1),
                record(1, 'miss', stream='mid_odds'), record(1, 'sent', stream='longshot'),
                record(4, 'pending')]
        counts = report.tally(at(13), rows)['24']
        self.assertEqual((counts['normal']['hits'], counts['normal']['judged']), (1, 2))
        self.assertEqual((counts['mid_odds']['hits'], counts['mid_odds']['judged']), (0, 1))
        self.assertEqual((counts['longshot']['hits'], counts['longshot']['judged']), (1, 1))
        self.assertEqual(report.tally(at(15), rows)['24']['normal']['hits'], 2)

    def test_zero_judged_is_not_zero_percent_and_pending_is_not_a_loss(self):
        prediction = {'day': '20260921', 'jcd': '08', 'rno': 1, 'deadline': '12:50',
                      'sent_at': at(12, 40).isoformat(), 'main': ['1-2-3']}
        snapshot = report.build_snapshot(at(13), [], [prediction], [])
        counts = snapshot['venues']['08']['normal']
        self.assertEqual(counts['judged'], 0)
        self.assertEqual(counts['pending'], 1)
        self.assertNotIn('0.0%', report.result_text(counts))

    def test_future_and_late_predictions_do_not_become_pending(self):
        prediction = {'day': '20260921', 'jcd': '08', 'rno': 1, 'deadline': '13:20',
                      'sent_at': at(12, 50).isoformat(), 'main': ['1-2-3']}
        future = dict(prediction, rno=2, sent_at=at(13, 5).isoformat())
        late = dict(prediction, rno=3, deadline='12:30')
        counts = report.tally(at(13), [], [prediction, future, late])
        self.assertEqual(counts['08']['normal']['pending'], 0)

    def test_prior_day_and_naive_timestamps_are_excluded(self):
        old = dict(record(1, 'sent'), day='20260920')
        naive = dict(record(2, 'sent'), sent_at='2026-09-21T12:00:00')
        self.assertEqual(report.tally(at(13), [old, naive]), {})

    def test_utc_timestamps_use_the_japanese_cutoff(self):
        row = dict(record(1, 'sent'), sent_at='2026-09-21T04:00:00+00:00')
        self.assertEqual(report.tally(at(13), [row])['24']['normal']['hits'], 1)

    def test_every_venue_fits_in_one_silent_discord_embed(self):
        rows = [record(rno, 'sent' if rno % 2 else 'miss', jcd=jcd, stream=stream)
                for jcd in report.base.VENUES for stream in report.STREAMS for rno in range(1, 13)]
        payload = report.build_snapshot(at(13), rows, [], [])['payload']
        self.assertEqual(payload['flags'], 4096)
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        embed = payload['embeds'][0]
        self.assertEqual(len(embed['fields']), 24)
        values = [embed['title'], embed['description'], embed['footer']['text']]
        values += [s for f in embed['fields'] for s in (f['name'], f['value'])]
        self.assertLess(sum(len(s.encode('utf-16-le')) // 2 for s in values), 6000)
        self.assertNotIn('@everyone', json.dumps(payload))

    def test_channel_cannot_fall_back_to_main(self):
        with patch.dict(report.os.environ, {'DISCORD_WEBHOOK_URL': 'https://example.test/main'}, clear=True):
            with self.assertRaises(RuntimeError):
                report.require_report_channel()

    def test_acknowledged_slot_is_not_posted_twice(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(report, 'DELIVERIES', Path(tmp)/'sent.jsonl'), patch.object(report, 'SNAPSHOTS', Path(tmp)/'snapshots'), patch.object(report, 'require_report_channel'), patch.object(report, 'report_destination_key', return_value='reports:test'), patch.object(report, 'build_snapshot', return_value=report.build_snapshot(at(13), [], [], [])):
            sender = Mock(return_value={'id': '123'})
            self.assertEqual(report.send_slot(at(13), sender=sender), 1)
            self.assertEqual(report.send_slot(at(13), sender=sender), 0)
            sender.assert_called_once()

    def test_failed_send_is_not_acknowledged_and_can_retry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(report, 'DELIVERIES', Path(tmp)/'sent.jsonl'), patch.object(report, 'SNAPSHOTS', Path(tmp)/'snapshots'), patch.object(report, 'require_report_channel'), patch.object(report, 'report_destination_key', return_value='reports:test'), patch.object(report, 'build_snapshot', return_value=report.build_snapshot(at(13), [], [], [])):
            sender = Mock(side_effect=TimeoutError)
            with self.assertRaises(TimeoutError):
                report.send_slot(at(13), sender=sender)
            self.assertFalse(report.DELIVERIES.exists())
            self.assertEqual(report.send_slot(at(13), sender=lambda _: {'id': '123'}), 1)

    def test_schedule_starts_tomorrow_and_only_sends_due_slots(self):
        with patch.object(report, 'send_slot', return_value=1) as send:
            self.assertEqual(report.send_due(at(22, day=20)), 0)
            self.assertEqual(report.send_due(at(12)), 0)
            self.assertEqual(report.send_due(at(15)), 2)
            self.assertEqual([call.args[0].hour for call in send.call_args_list], [13, 15])


if __name__ == '__main__':
    unittest.main()
