from datetime import datetime, timedelta
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from research.capture_v1.collector import Collector, read, atomic_state, REPOSITORY
from research.capture_v1.sources import PublicClient, identity, url, page_deadline, database_enrichment
from research.capture_v1 import parsers
from research.scenario_v2.engine import JST, digest, verify

META={"day":"20261017","jcd":"04","rno":1,"deadline":"12:00"}


def card():
    result='締切予定時刻 '+('12:00 '*12)
    for i in range(1,7):
        result+=f'<tbody><tr><td class="is-boatColor{i}">{i}</td><td>photo</td><td>{4000+i} / A1<br>選手{i}</td><td>F0<br>L0<br>0.15</td>'
        result+='<td>6.00<br>30.00<br>50.00</td><td>6.00<br>30.00<br>50.00</td><td>20<br>30.00<br>50.00</td><td>25<br>30.00<br>50.00</td></tr></tbody>'
    return result


def preview(ready=True):
    result='締切予定時刻 '+('12:00 '*12)
    for i in range(1,7):
        value=f'{6.7+i*.01:.2f}' if ready else '-'
        result+=f'<tbody><tr><td class="is-boatColor{i}">{i}</td><td>x</td><td>選手{i}</td><td>52.0kg</td><td>{value}</td><td>0.0</td><td>-</td><td></td></tr></tbody>'
        if ready:result+=f'<span class="table1_boatImage1Number">{i}</span><span class="table1_boatImage1Time">.12</span>'
    return result+'<div>風速 3m</div><div>波高 2cm</div>'


def outcome():
    result='<table><tbody><tr><td>3連単</td><td>1-2-3</td><td>¥1,000</td></tr></tbody></table>'
    for i in range(1,7):
        result+=f'<tr><td>{i}</td><td class="is-boatColor{i}">{i}</td><td>{4000+i} 選手{i}</td><td>1.50.0</td></tr>'
        result+=f'<span class="table1_boatImage1Number">{i}</span><span class="table1_boatImage1Time">.12</span>'
    return result+'<div>決まり手 逃げ</div>'


class Clock:
    def __init__(self,at="2026-10-17T11:30:00+09:00"):self.at=datetime.fromisoformat(at)
    def __call__(self):return self.at
    def set(self,at):self.at=datetime.fromisoformat(at)


class Client:
    def __init__(self,clock):self.clock=clock;self.calls=[];self.ready=True;self.fail=False;self.delay=0
    def read(self,kind,meta,max_age=60):
        self.calls.append(kind)
        if self.fail and kind=='beforeinfo':raise TimeoutError('simulated timeout')
        self.clock.at+=timedelta(seconds=self.delay)
        body=card() if kind=='racelist' else preview(self.ready) if kind=='beforeinfo' else outcome()
        return {"race_id":identity(meta),"fetched_at":self.clock().isoformat(),"url":url(kind,meta),"html":body}


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'out'
        self.clock=Clock();self.client=Client(self.clock)
        self.c=Collector(self.root,client=self.client,clock=self.clock,mode='replay')
    def tearDown(self):self.tmp.cleanup()

    def test_preparation_then_wait_for_publication(self):
        self.clock.set('2026-10-17T10:00:00+09:00')
        self.assertEqual(self.c.step(META)['phase'],'prepared')
        self.assertEqual(self.client.calls,['racelist'])
        self.clock.set('2026-10-17T11:10:00+09:00');self.client.ready=False
        self.assertEqual(self.c.step(META)['phase'],'waiting_exhibition')
        self.assertFalse((self.root/identity(META)/'forecast.json').exists())

    def test_full_cycle_and_frozen_remains_unchanged(self):
        self.assertEqual(self.c.step(META)['phase'],'exhibition_revision_saved')
        self.clock.set('2026-10-17T11:56:30+09:00')
        self.assertEqual(self.c.step(META)['phase'],'frozen_local_only')
        p=self.root/identity(META)/'forecast.json';before=p.read_bytes();verify(read(p))
        self.assertFalse(read(self.root/identity(META)/'local_receipt.json')['remote_checkpoint_verified'])
        self.clock.set('2026-10-17T12:04:00+09:00')
        self.assertEqual(self.c.step(META)['phase'],'reviewed')
        self.assertEqual(p.read_bytes(),before)
        report=read(self.root/identity(META)/'review.json')
        self.assertEqual(report['actual_trifecta'],'1-2-3')
        self.assertFalse(report['causal_tactics_verified'])
        count=len(self.client.calls);self.c.step(META)
        self.assertEqual(len(self.client.calls),count)

    def test_missed_exhibition_never_creates_forecast(self):
        self.client.ready=False;self.c.step(META)
        self.clock.set('2026-10-17T11:57:01+09:00')
        self.assertEqual(self.c.step(META)['phase'],'missed_cutoff')
        self.assertFalse((self.root/identity(META)/'forecast.json').exists())

    def test_http_delay_rechecks_cutoff(self):
        self.clock.set('2026-10-17T11:56:50+09:00');self.client.delay=8
        self.assertEqual(self.c.step(META)['phase'],'late_acquisition_not_frozen')
        self.assertFalse((self.root/identity(META)/'forecast.json').exists())

    def test_poll_backoff_applies_after_error(self):
        self.client.fail=True
        with self.assertRaises(TimeoutError):self.c.step(META)
        self.client.fail=False;n=len(self.client.calls)
        self.assertEqual(self.c.step(META)['phase'],'waiting_poll_interval')
        self.assertEqual(len(self.client.calls),n)

    def test_fresh_revision_freezes_without_extra_requests(self):
        self.clock.set('2026-10-17T11:55:50+09:00');self.c.step(META)
        self.clock.set('2026-10-17T11:56:20+09:00');n=len(self.client.calls)
        self.assertEqual(self.c.step(META)['phase'],'frozen_local_only')
        self.assertEqual(len(self.client.calls),n)

    def test_optional_foot_timeout_does_not_manufacture_measurements(self):
        self.c.fetch_foot=True
        self.c.foot_fetcher=lambda *args:(_ for _ in ()).throw(TimeoutError('foot timeout'))
        self.c.step(META)
        data=read(self.root/identity(META)/'latest_data.json')
        self.assertIn('TimeoutError',data['source']['foot_error'])
        self.assertTrue(all(b.get('straight_time') is None for b in data['boats']))

    def test_optional_foot_identity_and_future_observation(self):
        self.c.fetch_foot=True
        payload={'observed_at':'2026-10-17T12:00:00+09:00','source_url':'public','rows':[]}
        self.c.foot_fetcher=lambda *args:payload
        with self.assertRaises(ValueError):self.c.step(META)

    def test_future_snapshot_envelope_rejected(self):
        original=self.client.read
        def bad(*args,**kwargs):
            value=original(*args,**kwargs);value['fetched_at']='2026-10-18T00:00:00+09:00';return value
        self.client.read=bad
        with self.assertRaises(ValueError):self.c.step(META)

    def test_changed_deadline_rejected(self):
        with self.assertRaises(ValueError):self.c.step({**META,'deadline':'12:01'})

    def test_nested_outcome_in_cached_revision_rejected(self):
        self.c.step(META);p=self.root/identity(META)/'latest_data.json';d=read(p)
        d['environment']['hidden']={'actual_st':.1};atomic_state(p,d)
        self.clock.set('2026-10-17T11:56:00+09:00')
        # make cached data fresh while preserving its explicit replay status
        d['meta']['captured_at']='2026-10-17T11:55:30+09:00';atomic_state(p,d)
        with self.assertRaises(ValueError):self.c.step(META)

    def test_storage_never_overlaps_production_or_input(self):
        with self.assertRaises(ValueError):Collector(REPOSITORY/'data/new_research')
        with self.assertRaises(ValueError):Collector(self.root,db_root=self.root/'db')
        with self.assertRaises(ValueError):Collector(self.root,db_root=self.root.parent)

    def test_live_and_replay_cannot_mix_or_backdate(self):
        with self.assertRaises(ValueError):Collector(self.root,mode='live')
        other=Collector(Path(self.tmp.name)/'live',client=self.client,clock=self.clock)
        with self.assertRaises(ValueError):other.step({**META,'day':'20261016'})

    def test_independent_process_lock(self):
        import fcntl
        race=self.root/identity(META);race.mkdir()
        with (race/'capture.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.c.step(META)['phase'],'busy')
        self.assertFalse(self.client.calls)

    def test_result_save_can_resume_after_interruption(self):
        self.clock.set('2026-10-17T11:56:30+09:00');self.c.step(META)
        self.clock.set('2026-10-17T12:04:00+09:00');self.c.step(META)
        (self.root/identity(META)/'review.json').unlink();n=len(self.client.calls)
        self.assertEqual(self.c.step(META)['phase'],'reviewed')
        self.assertEqual(len(self.client.calls),n)

    def test_live_review_after_midnight_without_historical_creation(self):
        live=Collector(Path(self.tmp.name)/'live',client=self.client,clock=self.clock)
        self.clock.set('2026-10-17T11:56:30+09:00');live.step(META)
        self.clock.set('2026-10-18T00:01:00+09:00')
        self.assertEqual(live.step(META)['phase'],'reviewed')
        with self.assertRaises(ValueError):live.step({**META,'rno':2})

    def test_fresh_fusion_source_reuse_without_requests(self):
        from research.scenario_v2.tests.test_adapter_batch import source_fixture
        record,checkpoint=source_fixture()
        self.clock.set('2026-10-17T11:56:30+09:00')
        record.update(**META,key=identity(META),deadline_at='2026-10-17T12:00:00+09:00',
                      captured_at='2026-10-17T11:55:00+09:00',created_at='2026-10-17T11:56:00+09:00')
        record['pre_race_weather']['entry_observed']=True
        record['database']['snapshot_at']='2026-10-17T11:30:00+09:00'
        record['digest']=digest({k:v for k,v in record.items() if k!='digest'})
        checkpoint.update(key=record['key'],prediction_digest=record['digest'],prediction_committed_at='2026-10-17T11:56:01+09:00')
        source=Path(self.tmp.name)/'source'
        for kind,value in [('predictions',record),('checkpoints',checkpoint)]:
            path=source/kind/META['day']/(identity(META)+'.json');path.parent.mkdir(parents=True)
            path.write_text(json.dumps(value))
        collector=Collector(self.root,client=self.client,clock=self.clock,mode='replay',fusion_root=source)
        self.assertEqual(collector.step(META)['phase'],'frozen_local_only')
        self.assertEqual(self.client.calls,[])


class SourceTests(unittest.TestCase):
    def test_actual_official_input_fixtures_and_missing_deadline(self):
        raw=(REPOSITORY/'tests/fixtures/racelist-20260913-08-1.html').read_text()
        self.assertEqual(len(parsers.parse_racelist_boats(raw)),6)
        with self.assertRaises(ValueError):page_deadline(raw,1)
        raw=(REPOSITORY/'tests/fixtures/beforeinfo-20260913-08-1.html').read_text()
        parsed=parsers.parse_beforeinfo(raw)
        self.assertEqual(parsed['exhibition_count'],0)
        self.assertFalse(parsed['entry_observed'])
        raw=(REPOSITORY/'tests/fixtures/beforeinfo-20260912-08-3.html').read_text()
        self.assertEqual(parsers.parse_beforeinfo(raw)['exhibition_count'],6)

    def test_parse_card_and_exhibition_preserves_flying_and_zero_weight(self):
        self.assertEqual(len(parsers.parse_racelist_boats(card())),6)
        p=parsers.parse_beforeinfo(preview().replace('>.12</span>','>F.03</span>',1))
        self.assertEqual(p['boats'][1]['weight_kg'],52)
        self.assertEqual(p['boats'][1]['exhibition_st_timing'],-.03)
        self.assertEqual(p['exhibition_count'],6)
        self.assertTrue(p['entry_observed'])

    def test_parse_refund_and_unknown_result(self):
        self.assertEqual(parsers.parse_payout('未確定')['status'],'pending')
        x=parsers.parse_result(outcome(),'20261017','04',1)
        self.assertEqual(x['trifecta'],'1-2-3')
        self.assertEqual(x['finish'][0]['st'],.12)

    def test_cache_reuse_has_zero_network_calls(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/identity(META)/'beforeinfo.json';p.parent.mkdir()
            p.write_text(json.dumps({'race_id':identity(META),'url':url('beforeinfo',META),
                                     'fetched_at':clock().isoformat(),'html':preview()}))
            with patch('urllib.request.urlopen',side_effect=AssertionError('must not request')):
                got=PublicClient(tmp,clock).read('beforeinfo',META)
            self.assertTrue(got['cache_reused'])

    def test_future_db_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'meta.json').write_text(json.dumps({'snapshot_at':'2026-10-18T00:00:00+09:00'}))
            with self.assertRaises(ValueError):database_enrichment(p,[],META,'2026-10-17T11:00:00+09:00')

    def test_actual_official_result_fixture_contract(self):
        p=REPOSITORY/'tests/fixtures/raceresult-20260912-08-10.html'
        x=parsers.parse_result(p.read_text(),'20260912','08',10)
        self.assertEqual(len(x['finish']),6)
        self.assertEqual(len({b['racer_id'] for b in x['finish']}),6)
        self.assertGreater(x['payout_per_100'],0)


if __name__=='__main__':unittest.main()
