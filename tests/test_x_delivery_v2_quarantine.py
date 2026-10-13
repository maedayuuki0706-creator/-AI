from datetime import timedelta
import copy
import hashlib
from unittest.mock import Mock, patch
import unittest

from tests.test_x_delivery_v2 import MemoryStore
from x_delivery_v2 import dispatcher, quarantine
from x_delivery_v2.store import key, receipt_key
from x_delivery_policy import JST
from datetime import datetime


class SafeQuarantineTests(unittest.TestCase):
    def fixture(self):
        now=datetime(2026,10,12,13,tzinfo=JST)
        row={'day':'20261012','jcd':'23','rno':9,'venue':'唐津','deadline':'12:38',
             'post':'fixture only','picks':['1-2-3'],'source':'fixture','sent_at':'2026-10-12T12:20:00+09:00'}
        race,rkey=key(row),receipt_key(row,'result')
        receipt={'key':rkey,'phase':'result','status':'uncertain','owner':'a'*32,
                 'parent_post_id':'111111','claimed_at':'2026-10-12T12:45:22+09:00',
                 'row':row,'content_sha256':hashlib.sha256(row['post'].encode()).hexdigest()}
        reviewed={k:receipt[k] for k in ('owner','parent_post_id','content_sha256','claimed_at')}
        reviewed.update(reason='fixture HTTP503; outcome unknown',evidence='fixture only',automatic_resend_prohibited=True)
        store=MemoryStore();store.publish(row)
        store.states[row['day']]={'x_post_ids':{race:'111111'},'x_posted_races':[race],
             'x_v2_receipts':{rkey:receipt},'x_result_attempts':{race:{'id':'a'*32,'status':'uncertain','attempt':1}}}
        return now,row,rkey,store,reviewed

    def test_reviewed_uncertain_is_not_retried_or_falsely_marked_posted(self):
        now,row,rkey,store,reviewed=self.fixture();sender=Mock();before=copy.deepcopy(store.states)
        with patch.dict(quarantine.REVIEWED,{rkey:reviewed},clear=True):
            report=dispatcher.run_once(store=store,clock=lambda:now+timedelta(days=1),
                candidates=[],transport=sender,ready=Mock())
        self.assertEqual(report['status'],'checked_with_quarantine')
        self.assertEqual(report['x_monitor']['quarantined_transmissions'],1)
        self.assertEqual(report['x_monitor']['previous_day']['unresolved_api_attempt_count'],1)
        self.assertEqual(store.states,before)
        sender.assert_not_called()

    def test_fresh_or_unreviewed_uncertain_still_fails_the_health_check(self):
        now,row,rkey,store,reviewed=self.fixture();sender=Mock()
        with patch.dict(quarantine.REVIEWED,{},clear=True):
            report=dispatcher.run_once(store=store,clock=lambda:now,candidates=[],transport=sender,ready=Mock())
        self.assertEqual(report['status'],'degraded')
        self.assertEqual(len(report['held']),1)
        sender.assert_not_called()

    def test_changed_claim_cannot_reuse_review_or_send(self):
        now,row,rkey,store,reviewed=self.fixture();sender=Mock()
        store.states[row['day']]['x_v2_receipts'][rkey]['owner']='b'*32
        with patch.dict(quarantine.REVIEWED,{rkey:reviewed},clear=True),self.assertRaises(ValueError):
            dispatcher.deliver(row,'result',store=store,clock=lambda:now,transport=sender)
        sender.assert_not_called()

    def test_http503_evidence_survives_in_the_durable_uncertain_receipt(self):
        now,row,rkey,store,reviewed=self.fixture()
        store.states[row['day']]['x_result_attempts']={}
        store.states[row['day']]['x_v2_receipts']={}
        sender=Mock(return_value={'ok':False,'error':'X HTTP 503','transport_http_status':502})
        with patch.dict(quarantine.REVIEWED,{},clear=True):
            saved=dispatcher.deliver(row,'result',store=store,clock=lambda:now,transport=sender)
        self.assertEqual(saved['status'],'uncertain')
        self.assertEqual(saved['transport_evidence']['transport_http_status'],502)
        self.assertNotIn(key(row),store.states[row['day']].get('x_result_post_ids',{}))


if __name__=='__main__':
    unittest.main()
