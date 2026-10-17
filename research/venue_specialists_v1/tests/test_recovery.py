import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from research.venue_specialists_v1 import run,engine,review
from research.venue_specialists_v1.official import Official
from research.venue_specialists_v1.audit import coverage_counts
from research.venue_specialists_v1.tests.test_engine import fixture,VENUE_STATS,FakeOfficial,FakeTide,JST

class RecoveryTests(unittest.TestCase):
    def test_all_unvalidated_numeric_corrections_disabled(self):
        x=engine.analyze(fixture(),venues_db=VENUE_STATS,mode='replay',now='2026-10-27T12:00:00+09:00')
        for row in x['lane_audits']:
            for field in ['venue_course_prior_log','motor_residual','historical_st_formation','exhibition_time_relative']:
                self.assertEqual(row['components'][field],0)
        self.assertEqual(len(x['common_v2']['lanes']),6)
        self.assertTrue(all(h['attack_origin'] is not None for row in x['lane_audits'] for h in row['hypotheses']))

    def test_empty_schedule_is_not_silently_success(self):
        source=Official()
        source.fetch=lambda url: '<html>not a schedule</html>'
        with self.assertRaises(ValueError):source.deadlines('20261017','16')

    def test_verified_nonheld_venue_is_distinct(self):
        source=Official()
        source.fetch=lambda url: '<a href="?jcd=16">held</a>' if '/index?' in url else ''
        self.assertEqual(source.deadlines('20261017','03'),[])

    def test_inventory_detects_races_missed_by_all_ticks(self):
        now=datetime(2026,10,17,13,5,tzinfo=JST)
        class Source(FakeOfficial):
            def deadlines(self,*args):return [f'{10+i//2:02}:{(i%2)*30:02}' for i in range(12)]
        with TemporaryDirectory() as tmp:
            with patch.object(run,'collect_race',side_effect=TimeoutError('capture unavailable')):
                report=run.run(tmp,clock=lambda:now,official=Source(),max_workers=1)
            stats=coverage_counts(tmp,'20261017',now=now)
            self.assertEqual(report['scheduled_races'],24)
            self.assertEqual(stats['16']['missing_count'],7)
            self.assertEqual(stats['03']['missing_count'],7)
            self.assertEqual(report['health'],'degraded')
            self.assertEqual(stats['23']['operational_status'],'not_started')
            self.assertTrue(list((Path(tmp)/'attempts').glob('*/*.json')))

    def test_schedule_failure_is_reported(self):
        class Source(FakeOfficial):
            def deadlines(self,*args):raise TimeoutError('schedule unavailable')
        with TemporaryDirectory() as tmp:
            report=run.run(tmp,clock=lambda:datetime(2026,10,17,13,5,tzinfo=JST),official=Source())
            self.assertEqual(len(report['schedule_errors']),2)
            self.assertEqual(report['health'],'degraded')

    def test_receipt_verifies_both_original_and_forecast(self):
        at=datetime(2026,10,17,10,0,tzinfo=JST)
        with TemporaryDirectory() as tmp:
            run.collect_race('20261017','16',1,'10:25',tmp,clock=lambda:at,official=FakeOfficial(),tide_source=FakeTide())
            def show(sha,path):return (Path(tmp)/path.removeprefix('data/venue_specialists_v1/')).read_text()
            receipt=run.verify_commit(tmp,'a'*40,git_show=show,confirmed_at=at)[0]
            self.assertIn('snapshot_digest',receipt)
            (Path(tmp)/'receipts/20261017/20261017_16_01.json').unlink()
            input_path=Path(tmp)/'inputs/20261017/20261017_16_01.json'
            payload=json.loads(input_path.read_text());payload['boats'][0]['racer_id']='9999';input_path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):run.verify_commit(tmp,'a'*40,git_show=show,confirmed_at=at)

    def test_actual_result_wrong_race_rejected(self):
        from research.venue_specialists_v1.tests.test_review import fixture as pair
        forecast,receipt=pair()
        with self.assertRaises(ValueError):review.evaluate(forecast,receipt,{'race_id':'20261017_03_01','status':'settled','payouts':{'1-2-3':1000}})

if __name__=='__main__':unittest.main()

class ComparisonTests(unittest.TestCase):
    def test_comparison_uses_only_same_race_proven_baseline(self):
        from research.scenario_v2.tests.test_adapter_batch import source_fixture
        from research.venue_specialists_v1.compare import compare_record
        from research.venue_specialists_v1.tests.test_review import fixture as pair
        base,cp=source_fixture();f,receipt=pair()
        # Keep the real fixture timestamps and race identity internally consistent.
        f['race_id']=base['key'];f['digest']=engine.digest({k:v for k,v in f.items() if k!='digest'})
        receipt.update(race_id=f['race_id'],digest=f['digest'])
        settled=review.evaluate(f,receipt,{'status':'settled','payouts':{base['models']['fusion']['picks'][0]:1000}})
        row=compare_record(f,settled,base,cp)
        self.assertTrue(row['new_yuuki_hit']);self.assertEqual(row['stake_yen_each'],1000)
        cp['prediction_committed_at']=base['deadline_at']
        with self.assertRaises(ValueError):compare_record(f,settled,base,cp)

    def test_actual_details_flow_to_common_v2_review(self):
        from research.venue_specialists_v1.tests.test_review import fixture as pair
        f,receipt=pair()
        result={'status':'settled','observed_at':'2026-10-17T11:40:00+09:00','payouts':{'1-2-3':1000},'details':{
            'method':'逃げ','finish':[{'lane':i,'racer_id':str(5000+i),'finish':i,
                                      'course':i,'st':.15} for i in range(1,7)]}}
        row=review.evaluate(f,receipt,result)
        self.assertEqual(len(row['common_v2_diagnostics']['lanes']),6)
        self.assertTrue(row['main_head_correct'])
        self.assertFalse(row['scenario_mechanism_verified'])
