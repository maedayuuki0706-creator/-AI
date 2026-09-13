import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import prediction_recap as recap
from discord_formation import expand_formation


def row(rno=1, **extra):
    return dict(day='20260913', jcd='07', rno=rno, deadline='15:00',
                sent_at='2026-09-13T14:40:00+09:00', phase='final',
                main=['1-2-3', '1-2-4', '2-1-3'],
                cover=['2-1-4'], outsiders=['3-1-2'], **extra)


class PredictionRecapTests(unittest.TestCase):
    def test_one_venue_message_has_all_races_and_preserves_exact_sections(self):
        recaps, _ = recap.build_recaps('20260913', [row()], {'races': {'07:1': {}}}, [])
        self.assertEqual(len(recaps), 1)
        fields = recaps[0]['payload']['embeds'][0]['fields']
        self.assertEqual(len(fields), 12)
        self.assertIn('合計5点', fields[0]['name'])
        lines = fields[0]['value'].splitlines()
        for label, picks in [('本線', row()['main']), ('抑え', row()['cover']), ('穴', row()['outsiders'])]:
            index = next(i for i, line in enumerate(lines) if line.startswith('**' + label))
            actual = set().union(*(expand_formation(text) for text in lines[index + 1].split(' ／ ')))
            self.assertEqual(actual, set(picks))
        self.assertIn('配信記録なし', fields[1]['value'])
        self.assertLessEqual(recaps[0]['characters'], 6000)

    def test_late_delivery_cannot_replace_pre_close_prediction(self):
        late = {**row(), 'sent_at': '2026-09-13T15:01:00+09:00', 'main': ['6-5-4']}
        recaps, excluded = recap.build_recaps('20260913', [row(), late], {}, [])
        self.assertEqual(len(excluded), 1)
        self.assertNotIn('6-5-4', json.dumps(recaps))

    def test_withdrawal_notice_and_missing_prediction_are_distinct(self):
        notice = {**row(), 'status': 'withdrawn'}
        recaps, _ = recap.build_recaps('20260913', [], {'races': {'07:1': {}}}, [notice])
        fields = recaps[0]['payload']['embeds'][0]['fields']
        self.assertTrue(fields[0]['value'].startswith('欠場\n'))
        self.assertIn('配信記録なし', fields[1]['value'])

    def test_acknowledged_post_is_persisted_before_next_venue_and_not_resent(self):
        recaps, _ = recap.build_recaps('20260913', [row()], {}, [])
        with tempfile.TemporaryDirectory() as temp, patch.object(recap, 'DELIVERY_PATH', Path(temp)/'sent.jsonl'):
            with patch.object(recap, 'post_confirmed', return_value={'id': '123'}) as sender:
                recap.send_recaps(recaps, sender=sender, pause=lambda _: None)
                recap.send_recaps(recaps, sender=sender, pause=lambda _: None)
                self.assertEqual(sender.call_count, 1)
                self.assertEqual(recap.read_rows(recap.DELIVERY_PATH)[0]['message_id'], '123')

    def test_failed_post_is_not_recorded_as_delivered(self):
        recaps, _ = recap.build_recaps('20260913', [row()], {}, [])
        with tempfile.TemporaryDirectory() as temp, patch.object(recap, 'DELIVERY_PATH', Path(temp)/'sent.jsonl'):
            with patch.object(recap, 'post_confirmed', side_effect=RuntimeError('HTTP 403')) as sender:
                with self.assertRaises(RuntimeError):
                    recap.send_recaps(recaps, sender=sender, pause=lambda _: None)
            self.assertFalse(recap.DELIVERY_PATH.exists())

    def test_sender_requests_saved_message_and_uses_existing_notifier_identity(self):
        with patch.dict(recap.os.environ, {'DISCORD_WEBHOOK_URL': 'https://example.test/hook?thread_id=1'}), patch.object(recap.urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'{"id":"123"}'
            message = recap.post_confirmed({'embeds': []})
            self.assertEqual(message['id'], '123')
            sent = request.call_args.args[0]
            self.assertIn('wait=true', sent.full_url)
            self.assertIn('thread_id=1', sent.full_url)
            self.assertEqual(sent.get_header('User-agent'), recap.base.UA)


if __name__ == '__main__':
    unittest.main()
