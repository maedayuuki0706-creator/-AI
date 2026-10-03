from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

import sokuhou_health as health


class SokuhouHealthTests(unittest.TestCase):
    def audit(self, row):
        with patch.object(health.delivery, 'paused', return_value=False), \
             patch.object(health.delivery.STORE, 'ensure'), \
             patch.object(health, 'git', side_effect=[b'',b'head',b'data/sokuhou_receipts/20261003/normal_24_10.json\n']), \
             patch.object(health, 'content', return_value=json.dumps(row).encode()), \
             patch.object(health, 'print', create=True):
            return health.audit('20261003')

    def test_confirmed_receipt_is_healthy(self):
        self.assertEqual(self.audit({'key':'normal:20261003:24:10','status':'sent','message_id':'123'}),0)

    def test_uncertain_send_requires_review(self):
        self.assertEqual(self.audit({'key':'normal:20261003:24:10','status':'uncertain'}),1)

    def test_another_active_writer_is_not_falsely_flagged_but_stale_claim_is(self):
        row={'key':'normal:20261003:24:10','status':'sending','claimed_at':datetime.now(timezone.utc).isoformat()}
        self.assertEqual(self.audit(row),0)
        row['claimed_at']=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat()
        self.assertEqual(self.audit(row),1)


if __name__ == '__main__':
    unittest.main()
