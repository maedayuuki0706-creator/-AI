import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_report
import direct_discord_notify as predictions
import prediction_recap as reports

PREDICTION_URL = 'https://example.test/api/webhooks/111/example-a'
REPORT_URL = 'https://example.test/api/webhooks/222/example-b'


class ReportChannelTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target,attr,value in [(reports.base.delivery,'OUTBOX_ROOT',Path(tmp.name)/'outbox'),(reports.base.audit,'AUDIT_ROOT',Path(tmp.name)/'audit')]:
            item=patch.object(target,attr,value)
            item.start();self.addCleanup(item.stop)

    def test_daily_report_and_predictions_choose_different_destinations(self):
        with patch.dict(reports.os.environ, {'DISCORD_WEBHOOK_URL': PREDICTION_URL,
                                            'DISCORD_REPORT_WEBHOOK_URL': REPORT_URL}, clear=True), patch.object(reports.urllib.request, 'urlopen') as send:
            response = send.return_value.__enter__.return_value
            response.read.return_value = b'{"id":"123","channel_id":"456"}'
            response.status = 200
            reports.post_confirmed({'content': 'daily report'})
            predictions.send_discord('prediction')
            targets = [call.args[0].full_url for call in send.call_args_list]
            self.assertTrue(targets[0].startswith(REPORT_URL + '?'))
            self.assertIn('wait=true', targets[0])
            self.assertEqual(targets[1], PREDICTION_URL+'?wait=true')

    def test_unconfigured_report_destination_preserves_current_delivery(self):
        with patch.dict(reports.os.environ, {'DISCORD_WEBHOOK_URL': PREDICTION_URL,
                                            'DISCORD_REPORT_WEBHOOK_URL': '  '}, clear=True):
            self.assertEqual(reports.report_webhook_url(), PREDICTION_URL)
            self.assertEqual(reports.report_destination_key(), 'predictions')

    def test_recap_can_move_to_new_channel_once_without_reposting_old_channel(self):
        recap = {'day': '20260913', 'jcd': '08', 'venue': '常滑', 'digest': 'original',
                 'predicted_races': 12, 'payload': {'content': 'recap'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(reports, 'DELIVERY_PATH', Path(tmp)/'sent.jsonl'), patch.dict(reports.os.environ, {'DISCORD_WEBHOOK_URL': PREDICTION_URL}, clear=True):
            reports.DELIVERY_PATH.write_text(json.dumps({'day':'20260913','jcd':'08','digest':'original','message_id':'120'})+'\n')
            with patch.object(reports, 'post_confirmed', return_value={'id':'123','channel_id':'456'}) as sender:
                reports.send_recaps([recap], sender=sender, pause=lambda _: None)
                sender.assert_not_called()
                reports.os.environ['DISCORD_REPORT_WEBHOOK_URL'] = REPORT_URL
                reports.send_recaps([recap], sender=sender, pause=lambda _: None)
                reports.send_recaps([recap], sender=sender, pause=lambda _: None)
                self.assertEqual(sender.call_count, 1)
                key = reports.report_destination_key()
                reports.os.environ['DISCORD_REPORT_WEBHOOK_URL'] = REPORT_URL.replace('example-b','rotated')
                self.assertEqual(reports.report_destination_key(), key)
                reports.send_recaps([recap], sender=sender, pause=lambda _: None)
                self.assertEqual(sender.call_count, 1)

    def test_daily_report_deduplication_also_includes_destination(self):
        payload = {'embeds': [{'title': '常滑｜日報'}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(daily_report, 'SENT_PATH', Path(tmp)/'sent.jsonl'), patch.dict(reports.os.environ, {'DISCORD_WEBHOOK_URL': PREDICTION_URL}, clear=True), patch('daily_report_format.report_payloads', return_value=[payload]), patch.object(reports, 'post_confirmed', return_value={'id':'123','channel_id':'456'}) as send, patch.object(daily_report.time, 'sleep'):
            self.assertEqual(daily_report.send_report({'day':'20260913'}), 1)
            self.assertEqual(daily_report.send_report({'day':'20260913'}), 0)
            reports.os.environ['DISCORD_REPORT_WEBHOOK_URL'] = REPORT_URL
            self.assertEqual(daily_report.send_report({'day':'20260913'}), 1)
            self.assertEqual(daily_report.send_report({'day':'20260913'}), 0)
            self.assertEqual(send.call_count, 2)


if __name__ == '__main__':
    unittest.main()
