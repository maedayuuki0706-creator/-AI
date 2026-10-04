import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

import prototype3_delivery as yuuki
from delivery_v2 import guard, integration, receipts
from delivery_v2.store import FileStore


class IntegrationTests(unittest.TestCase):
    def test_durable_yuuki_receipt_survives_legacy_receipt_loss(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            now = yuuki.now_jst()
            record = {'day':now.strftime('%Y%m%d'),'jcd':'01','rno':1,'deadline':(now+timedelta(minutes=10)).strftime('%H:%M'),
                      'key':now.strftime('%Y%m%d')+'_01_01','digest':'original','selection':{'selected':False}}
            with patch.object(yuuki,'ROOT',root/'legacy'), patch.object(receipts,'ROOT',root/'state'), \
                 patch.object(guard,'RECOVERY',root/'recovery'), patch.object(integration,'default_store',side_effect=FileStore), \
                 patch.dict('os.environ',{'PT3_DISCORD_WEBHOOK_URL':'https://example.test/hook','DISCORD_DELIVERY_V2_STREAMS':'yuuki'},clear=True), \
                 patch.object(yuuki,'message',return_value='original picks'), patch.object(yuuki,'post_webhook',return_value='123456') as post:
                yuuki.deliver(record)
                first = yuuki.read(yuuki.receipt_path(record['key']))
                yuuki.receipt_path(record['key']).unlink()
                yuuki.prediction_path(record['key']).unlink()
                yuuki.deliver({**record,'digest':'different prediction after state loss'})
                self.assertEqual(yuuki.read(yuuki.receipt_path(record['key'])),first)
                self.assertEqual(yuuki.read(yuuki.prediction_path(record['key'])),record)
                post.assert_called_once()
                self.assertEqual(first['message_id'],'123456')

    def test_existing_legacy_receipt_is_not_replayed_during_migration(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(yuuki,'ROOT',Path(temp)/'legacy'), patch.object(receipts,'ROOT',Path(temp)/'state'), patch.object(integration,'default_store',side_effect=FileStore), \
             patch.dict('os.environ',{'PT3_DISCORD_WEBHOOK_URL':'https://example.test/hook','DISCORD_DELIVERY_V2_STREAMS':'yuuki'},clear=True), \
             patch.object(yuuki.trial,'before_deadline',return_value=True), patch.object(yuuki,'post_prediction') as post:
            record={'key':'20261004_01_01','day':'20261004','jcd':'01','rno':1,'deadline':'23:59','selection':{'selected':False}}
            yuuki.trial.write_json(yuuki.receipt_path(record['key']),{'key':record['key'],'delivered_at':'2026-10-04T10:00:00+09:00'})
            yuuki.deliver(record)
            post.assert_not_called()
            stored,_ = FileStore().read(receipts.identity('yuuki','20261004','01',1))
            self.assertEqual(stored['status'],'legacy_unverified')


if __name__ == '__main__': unittest.main()
