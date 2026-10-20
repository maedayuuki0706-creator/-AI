import json,tempfile,unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from .collector import Store,once,encode,parse_odds,capture,JST,result_environment
from .supplement import tides,karatsu_foot

class EvidenceTests(unittest.TestCase):
    def test_once_conflict_preserves_original(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';self.assertTrue(once(p,b'first'));self.assertFalse(once(p,b'first'))
            with self.assertRaises(ValueError):once(p,b'changed')
            self.assertEqual(p.read_bytes(),b'first')
    def test_raw_hash_validation_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);doc=s.document('official',{'url':'https://example.test','retrieved_at':'2026-10-20T12:00:00+09:00'})
            self.assertEqual(s.body(doc),'official');doc['sha256']='0'*64
            with self.assertRaises(ValueError):s.body(doc)
    def test_storage_cannot_be_existing_repository(self):
        from .collector import ROOT
        with self.assertRaises(ValueError):Store(ROOT/'data/materials')
    def test_reused_completed_race_never_fetches_or_backdates_odds(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);once(Path(d)/'reused_inputs/20261020_03_01.json',encode({'meta':{'deadline':'11:00'}}))
            with patch('research.materials_v1.collector.now',return_value=datetime(2026,10,20,12,0,tzinfo=JST)),patch.object(s,'get',side_effect=AssertionError('must not fetch')):
                r=capture(s,'20261020','03',1)
            self.assertEqual(r['http_requests'],0)
            for p in (Path(d)/'odds_targets/20261020').glob('*.json'):
                r=json.loads(p.read_text());self.assertEqual(r['status'],'missed');self.assertNotIn('odds',r)
    def test_prediction_parser_whitespace_zero_negative_and_missing_extrema(self):
        line=''.join(f'{x:3d}' for x in [-2,0]+[50]*22)+'26 1 1TK'+' 4 8169'+'9999999'*3+' 9 1 -2'+'9999999'*3
        self.assertEqual(len(line),136)
        h,e=tides(line,'TK');self.assertEqual(len(h),24);self.assertEqual(h[0]['height_cm'],-2);self.assertEqual(h[1]['height_cm'],0)
        self.assertEqual([x['kind'] for x in e],['high','low']);self.assertIn('T04:08',e[0]['at'])
        with self.assertRaises(ValueError):tides(line,'UN')
    def test_incomplete_odds_not_silently_filled(self):
        with self.assertRaises(ValueError):parse_odds('<html>not published</html>')
    def test_incomplete_foot_is_unknown(self):
        with self.assertRaises(ValueError):karatsu_foot('<html>not published</html>')
    def test_result_weather_never_renames_actual_start_as_exhibition(self):
        r=result_environment('<html><span class="table1_boatImage1Number">1</span><span class="table1_boatImage1Time">.12</span></html>')
        self.assertNotIn('boats',r);self.assertNotIn('exhibition_st',r);self.assertNotIn('entry_observed',r)
    def _remote_mock(self,root,*args):
        from .worker import STATE_BRANCH
        if args[:2]==('branch','--show-current'):return STATE_BRANCH
        if args[0]=='status':return '?? evidence.json'
        if args[:2]==('rev-parse','HEAD'):return 'a'*40
        if args[0]=='ls-remote':return 'a'*40+'\trefs/heads/'+STATE_BRANCH
        return ''
    def _response(self,sha):
        r=BytesIO(json.dumps({'object':{'sha':sha}}).encode());r.headers={'Date':'Tue, 20 Oct 2026 08:00:00 GMT'};return r
    def test_old_remote_ref_retried_before_acknowledgement(self):
        from .worker import publish
        with tempfile.TemporaryDirectory() as d,patch('research.materials_v1.worker.git',side_effect=self._remote_mock),patch('research.materials_v1.worker.now',return_value=datetime(2026,10,20,17,0,tzinfo=JST)),patch('research.materials_v1.worker.time.sleep'),patch('research.materials_v1.worker.urllib.request.urlopen',side_effect=[self._response('b'*40),self._response('a'*40)]) as fetch:
            r=publish(Store(d));self.assertEqual(r['remote_commit'],'a'*40);self.assertEqual(fetch.call_count,2)
    def test_unconfirmed_remote_api_never_becomes_prospective_receipt(self):
        from .worker import publish
        with tempfile.TemporaryDirectory() as d,patch('research.materials_v1.worker.git',side_effect=self._remote_mock),patch('research.materials_v1.worker.now',return_value=datetime(2026,10,20,17,0,tzinfo=JST)),patch('research.materials_v1.worker.time.sleep'),patch('research.materials_v1.worker.urllib.request.urlopen',side_effect=[self._response('b'*40) for _ in range(3)]):
            r=publish(Store(d));self.assertEqual(r['status'],'git_saved_api_ack_pending');self.assertEqual(r['new_forecast_receipts'],0)
            p=next((Path(d)/'persistence_pending').glob('*.json'));self.assertFalse(json.loads(p.read_text())['prospective_receipt_confirmed'])

if __name__=='__main__':unittest.main()
