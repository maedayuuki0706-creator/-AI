from copy import deepcopy
import base64
import gzip
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .application import Materials, _apply_profile, build, load_foot
from .review import review
from research.scenario_v2 import engine as scenario


def snapshot():
    boats = []
    for lane in range(1, 7):
        boats.append({'lane': lane, 'course': lane, 'predicted_course': lane,
                      'racer_id': str(4000 + lane), 'name': '選手' + str(lane),
                      'avg_st': .11 if lane == 4 else .14, 'exhibition_st': .10,
                      'exhibition_time': 6.60 + lane / 100, 'motor_number': lane,
                      'motor_top2_rate': 40.0, 'motor_top3_rate': 60.0,
                      'boat_top2_rate': 30.0, 'boat_top3_rate': 50.0,
                      'win_rate': 6.0, 'top2_rate': 40.0, 'top3_rate': 60.0,
                      'local_win_rate': 6.0, 'local_top2_rate': 40.0})
    return {'meta': {'day': '20261021', 'jcd': '23', 'rno': 12, 'deadline': '16:36',
                     'captured_at': '2026-10-21T16:08:40+09:00'},
            'boats': boats, 'environment': {'wind_speed': 3.0, 'wave_cm': 2.0}}


def fixtures(root, *, observation='2026-10-21T16:14:00+09:00'):
    (root / 'derived').mkdir()
    profiles = []
    histories = []
    for lane in range(1, 7):
        profiles.append({'racer_id': str(4000 + lane), 'dimension': 'course', 'group': str(lane),
                         'period_start': '2026-01-01', 'period_end': '2026-10-17',
                         'denominator': 10, 'wins': 2, 'top2_count': 5, 'top3_count': 7,
                         'mean_actual_st': .14, 'winning_methods': {'逃げ' if lane == 1 else 'まくり': 2}})
        histories.append({'racer_id': str(4000 + lane), 'race_id': '202610172301',
                          'lane': lane, 'venue_code': '23', 'motor_number': lane,
                          'cycle_id': 'previous_machine', 'day': '2026-10-17',
                          'finish': lane, 'actual_course': lane, 'actual_st': .14})
        histories.append({'racer_id': str(4000 + lane), 'race_id': '202610172302',
                          'lane': lane, 'venue_code': '23', 'motor_number': lane,
                          'cycle_id': 'current_machine', 'day': '2026-10-17',
                          'finish': lane, 'actual_course': lane, 'actual_st': .14})
    for name, value in [('racer_tendencies', profiles), ('motor_race_histories', histories)]:
        (root / 'derived' / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')
    (root / 'original_foot').mkdir()
    (root / 'raw').mkdir()
    cells = []
    for b in snapshot()['boats']:
        lane = b['lane']
        values = [lane, b['name'], b['motor_number'], b['exhibition_time'], 37 + lane / 10,
                  5.0 if lane == 4 else 5.3 + lane / 100,
                  7.0 if lane == 6 else 7.1 if lane == 4 else 7.3 + lane / 100, 4]
        cells.append('<tr>' + ''.join('<td>' + str(x) + '</td>' for x in values) + '</tr>')
    raw = ('2026/10/21<table class="oriten">' + ''.join(cells) + '</table>').encode()
    (root / 'raw/source.gz.b64').write_bytes(base64.b64encode(gzip.compress(raw)))
    doc = {'race_id': '20261021_23_12',
           'acquisition': {'status': 'ok', 'retrieved_at': observation,
                           'url': 'https://www.boatrace-karatsu.jp/sp/index.php?page=yosou-cyokuzen&race=12',
                           'raw_path': 'raw/source.gz.b64', 'sha256': sha256(raw).hexdigest()}}
    (root / 'original_foot/20261021_23_12_x.json').write_text(json.dumps(doc), encoding='utf-8')


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixtures(self.root)
        self.materials = Materials(self.root, loaded_at='2026-10-20T22:00:00+09:00')

    def tearDown(self):
        self.temp.cleanup()

    def build(self, snap=None):
        snap = snap or snapshot()
        payload = {'race': {'venue': '唐津', 'wind_speed': 3.0},
                   'boats': deepcopy(snap['boats']), 'trifecta_odds': {}}
        with patch('research.materials_application_v1.application.from_frozen_official',
                   return_value={'payload': payload}):
            return build(snap, self.materials, state_root=self.root,
                         mode='live', now='2026-10-21T16:15:00+09:00')

    def test_real_engines_receive_history_and_measured_times(self):
        result = self.build()
        self.assertEqual(len(result['all_six']), 6)
        self.assertEqual(result['foot_provenance']['status'], 'joined')
        self.assertEqual(result['all_six'][3]['measured_foot']['turn_time']['same_race_rank'], 1)
        self.assertEqual(result['all_six'][5]['measured_foot']['straight_time']['same_race_rank'], 1)
        branch = next(h for h in result['all_six'][3]['hypotheses'] if h['tactic'] == 'まくり')
        self.assertEqual(branch['supported_observations'], 2)
        for card in result['model_cards'].values():
            self.assertEqual(len(set(card)), 10)
        self.assertFalse(result['result_accessed'])
        self.assertFalse(result['count_as_prospective'])
        scenario.verify(result)

    def test_raw_input_and_acquired_history_are_unchanged(self):
        snap = snapshot()
        previous = deepcopy(snap)
        files = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.build(snap)
        self.assertEqual(snap, previous)
        self.assertEqual(files, {p: p.read_bytes() for p in files})

    def test_data_effect_is_separate_from_prior_filling(self):
        result = self.build()
        change = result['card_changes']['course_prior_control -> acquired_course_profiles']
        self.assertTrue(change['added'])
        self.assertIn('course_prior_control', result['model_cards'])

    def test_official_fields_are_not_overwritten(self):
        b = {'lane': 1, 'course_win_rate': 70.0, 'course_top2_rate': 80.0}
        profile = self.materials.profile('4001', 1, '20261021')
        _apply_profile(b, profile)
        self.assertEqual(b['course_win_rate'], 70.0)
        self.assertEqual(b['course_top2_rate'], 80.0)

    def test_earlier_target_does_not_use_future_aggregate_or_current_result(self):
        p = self.materials.profile('4001', 1, '20261017')
        self.assertEqual(p['denominator'], 0)
        self.assertFalse(p['methods_known'])

    def test_motor_generations_are_not_combined_or_scored(self):
        value = self.materials.motor_context('23', 1, '20261021')
        self.assertEqual(len(value['separate_periods']), 2)
        self.assertFalse(value['current_cycle_verified'])
        self.assertEqual(value['model_fields_applied'], [])

    def test_nested_outcome_rejected_before_core_called(self):
        snap = snapshot()
        snap['source'] = {'nested': {'actual_st': .05}}
        with patch('research.materials_application_v1.application.from_frozen_official') as core:
            with self.assertRaisesRegex(ValueError, 'Outcome field'):
                build(snap, self.materials, mode='replay')
            core.assert_not_called()

    def test_future_material_load_cannot_be_claimed_live(self):
        self.materials.loaded_at = '2026-10-22T00:00:00+09:00'
        with self.assertRaisesRegex(ValueError, 'loaded after generation'):
            self.build()

    def test_raw_measurement_hash_and_roster_are_checked(self):
        snap = snapshot()
        snap['boats'][0]['name'] = '別人'
        with self.assertRaisesRegex(ValueError, 'roster name mismatch'):
            load_foot(self.root, snap, mode='replay', at='2026-10-21T18:00:00+09:00')
        path = self.root / 'original_foot/20261021_23_12_x.json'
        doc = json.loads(path.read_text());doc['acquisition']['sha256'] = '0' * 64
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, 'raw hash mismatch'):
            load_foot(self.root, snapshot(), mode='replay', at='2026-10-21T18:00:00+09:00')

    def test_late_measurements_are_explicit_replay_only(self):
        path = self.root / 'original_foot/20261021_23_12_x.json'
        doc = json.loads(path.read_text());doc['acquisition']['retrieved_at'] = '2026-10-21T17:00:00+09:00'
        path.write_text(json.dumps(doc))
        live = load_foot(self.root, snapshot(), mode='live', at='2026-10-21T18:00:00+09:00')
        replay = load_foot(self.root, snapshot(), mode='replay', at='2026-10-21T18:00:00+09:00')
        self.assertEqual(live['status'], 'excluded')
        self.assertEqual(replay['status'], 'joined')
        self.assertFalse(replay['available_before_deadline'])

    def test_independent_review_records_entry_change_without_mutating_forecast(self):
        frozen = self.build()
        previous = deepcopy(frozen)
        finish = [{'lane': i, 'racer_id': str(4000 + i), 'finish': i, 'course': i,
                   'status': 'finished'} for i in range(1, 7)]
        finish[3]['course'], finish[4]['course'] = 5, 4
        result = {'race_id': frozen['race_id'], 'acquisition': {'retrieved_at': '2026-10-21T17:00:00+09:00'},
                  'payout': {'status': 'settled', 'refund_lanes': []},
                  'details': {'finish': finish, 'trifecta': '1-2-3', 'payout_per_100': 1000}}
        row = review(frozen, result)
        self.assertEqual(len(row['entry_changes']), 2)
        self.assertFalse(row['actual_tactics_verified'])
        self.assertEqual(frozen, previous)
        result['race_id'] = '20261021_23_11'
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            review(frozen, result)

    def test_history_observed_in_future_rejected_in_live_mode(self):
        self.materials.latest_history_observed_at = scenario.aware('2026-10-22T00:00:00+09:00')
        with self.assertRaisesRegex(ValueError, 'source observed after generation'):
            self.build()


if __name__ == '__main__':
    unittest.main()
