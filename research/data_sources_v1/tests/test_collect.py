import copy
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from research.data_sources_v1.collect import Client, modern, supplement, legacy, days, digest
from research.data_sources_v1.train import feature_vector, split_days


def fixture():
    row={'date':'2026-10-17','stadium_number':3,'race_number':1,
         'closed_at':'2026-10-17 11:00:00',
         'racers':{str(i):{'entry_number':i,'number':4000+i,'motor_number':i,
                          'average_start_timing':.15} for i in range(1,7)},
         'preview':{'racers':{str(i):{'entry_number':i,'course_number':i,
                                      'start_timing':-.03 if i==3 else .1,
                                      'parts':[],'tilt_adjustment':0} for i in range(1,7)}},
         'result':{'refunds':[],'racers':{str(i):{'number':4000+i,'place_number':i} for i in range(1,7)}}}
    official={'normal_eligible':True,'boats':[{'lane':i,'racer_id':str(4000+i),
                'motor_number':i,'finish':i} for i in range(1,7)]}
    return row,official


class Contracts(unittest.TestCase):
    def test_signed_exhibition_flying_and_true_zero_preserved(self):
        row,official=fixture();x=supplement('202610170301',row,[],official)
        self.assertEqual(x['boats'][2]['exhibition_st'],-.03)
        self.assertEqual(x['boats'][0]['tilt'],0)

    def test_empty_arrays_known_null_unknown(self):
        row,official=fixture();row['preview']['racers']['2']['parts']=None
        x=supplement('202610170301',row,[],official)
        self.assertEqual(x['boats'][0]['parts'],[])
        self.assertIsNone(x['boats'][1]['parts'])
        self.assertEqual(x['refund_lanes'],[])

    def test_propeller_no_exchange_is_known_false_not_missing(self):
        row,official=fixture()
        row['preview']['racers']['1'].update(exhibition_time=6.8,propeller=None)
        x=supplement('202610170301',row,[],official)
        self.assertIs(x['boats'][0]['propeller_exchange'],False)
        self.assertIsNone(x['boats'][1]['propeller_exchange'])

    def test_zero_average_st_is_not_speed(self):
        row,official=fixture();row['racers']['1']['average_start_timing']=0
        self.assertIsNone(supplement('202610170301',row,[],official)['boats'][0]['average_st'])

    def test_wrong_day_rejected(self):
        row,_=fixture();payload={'programs':{'stadiums':{'3':{'races':{'1':row}}}}}
        with self.assertRaisesRegex(ValueError,'identity'):
            modern(payload,'2026-10-16')

    def test_wrong_result_race_rejected(self):
        row,_=fixture();row['result'].update(date=row['date'],stadium_number=3,race_number=2)
        with self.assertRaisesRegex(ValueError,'identity'):
            modern({'programs':{'stadiums':{'3':{'races':{'1':row}}}}},row['date'])

    def test_racer_mismatch_quarantines(self):
        row,official=fixture();official['boats'][0]['racer_id']='5999'
        with self.assertRaisesRegex(ValueError,'racer mismatch'):
            supplement('202610170301',row,[],official)

    def test_motor_mismatch_quarantines(self):
        row,official=fixture();official['boats'][0]['motor_number']=99
        with self.assertRaisesRegex(ValueError,'motor mismatch'):
            supplement('202610170301',row,[],official)

    def test_withdrawn_motor_uses_official_program_not_invention(self):
        row,official=fixture();official['boats'][0].update(motor_number=None,program={'motor_number':1})
        x=supplement('202610170301',row,[],official)
        self.assertTrue(x['official_motor_identity_verified'])

    def test_unknown_official_motor_does_not_become_verified(self):
        row,official=fixture();official['boats'][0]['motor_number']=None
        x=supplement('202610170301',row,[],official)
        self.assertFalse(x['official_motor_identity_verified'])
        self.assertFalse(x['official_normal_eligible'])

    def test_conflict_keeps_official_and_excludes_training(self):
        row,official=fixture();row['result']['racers']['1']['place_number']=2
        before=copy.deepcopy(official);x=supplement('202610170301',row,[],official)
        self.assertEqual(official,before)
        self.assertEqual(x['boats'][0]['official_finish'],1)
        self.assertFalse(x['official_normal_eligible']);self.assertTrue(x['conflicts'])

    def test_nonfinish_encodings_are_kept_separately_and_excluded(self):
        row,official=fixture();official['boats'][0]['finish']=0
        row['result']['racers']['1']['place_number']=99
        x=supplement('202610170301',row,[],official)
        self.assertFalse(x['conflicts'])
        self.assertTrue(x['status_encoding_differences'])
        self.assertFalse(x['official_normal_eligible'])

    def test_different_mirrors_are_one_upstream(self):
        row,official=fixture();x=supplement('202610170301',row,[{'source':'a'},{'source':'b'}],official)
        self.assertEqual(x['independent_evidence_count'],1)
        self.assertFalse(x['prospective_verified'])

    def test_empty_day_is_not_no_race(self):
        with self.assertRaises(ValueError):modern({'programs':{'stadiums':{}}},'2026-10-17')

    def test_legacy_duplicate_race_rejected(self):
        row={'date':'2025-10-18','stadium_number':3,'number':1,'boats':[]}
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            legacy({'programs':[row,row]},'2025-10-18','programs')

    def test_corrupted_cache_rejected_before_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'downloads'/'turnmark').mkdir(parents=True);(root/'raw').mkdir()
            (root/'raw'/'x.gz').write_bytes(gzip.compress(b'{}'))
            (root/'downloads'/'turnmark'/'2026-10-17.json').write_text(json.dumps(
                {'status':'ok','raw_path':'raw/x.gz','sha256':digest(b'wrong')}))
            with self.assertRaisesRegex(ValueError,'digest'):
                Client(root).read('turnmark','2026-10-17')

    def test_future_day_cannot_be_backfilled(self):
        tomorrow=(date.today()+timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):days('2026-01-01',tomorrow)

    def test_outcomes_and_odds_cannot_change_features(self):
        row,official=fixture();r=supplement('202610170301',row,[],official)
        original=feature_vector(r,r['boats'][0],True)
        r['api_result']={'place_number':1,'payouts':999999};r['historical_odds']={'1':9999}
        r['boats'][0]['official_finish']=6;r['boats'][0]['official_actual_st']=.01
        after=feature_vector(r,r['boats'][0],True)
        # NaNs compare unequal, so compare the stable text representations.
        self.assertEqual(str(original),str(after))

    def test_chronological_split_keeps_whole_days(self):
        rows=[{'day':(date(2026,1,1)+timedelta(days=i)).isoformat()} for i in range(40) for _ in range(2)]
        a,b,c=split_days(rows)
        self.assertLess(max(x['day'] for x in a),min(x['day'] for x in b))
        self.assertLess(max(x['day'] for x in b),min(x['day'] for x in c))
        self.assertEqual(len(a)+len(b)+len(c),len(rows))


if __name__=='__main__':unittest.main()
