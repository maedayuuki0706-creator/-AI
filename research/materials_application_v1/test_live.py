"""Failure-oriented contracts for prospective evidence and isolated operation."""
import base64
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .application import Materials, build, load_foot
from .context import enrich, tide_context
from .prepared import PreparedMaterials, SEED
from .live import publish, remote_ack, preinspection
from .settle import receipt_eligible, summarize
from .test_application import fixtures, snapshot
from research.materials_v1.collector import Store, encode, JST
from research.scenario_v2 import engine as scenario


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        fixtures(self.root)
        self.materials = Materials(self.root, loaded_at='2026-10-20T22:00:00+09:00')

    def tearDown(self):
        self.temp.cleanup()

    def frozen(self):
        snap = snapshot()
        payload = {'race': {'venue': '唐津'}, 'boats': deepcopy(snap['boats']), 'trifecta_odds': {}}
        with patch('research.materials_application_v1.application.from_frozen_official', return_value={'payload': payload}):
            f = build(snap, self.materials, state_root=self.root, mode='live', now='2026-10-21T16:15:00+09:00')
        ib = encode(snap); fb = encode(f)
        receipt = {'race_id': f['race_id'], 'remote_ref': 'research-materials-applied-state-v1',
            'forecast_sha256': sha256(fb).hexdigest(), 'input_sha256': sha256(ib).hexdigest(),
            'checked_at': '2026-10-21T16:30:00+09:00',
            'github_server_date': 'Wed, 21 Oct 2026 07:30:00 GMT',
            'confirmed_at_least_three_minutes_before_deadline': True, 'count_as_prospective': True}
        return f, receipt, ib, fb

    def test_valid_external_receipt_required_and_original_unchanged(self):
        f, r, ib, fb = self.frozen(); original = deepcopy(f)
        self.assertTrue(receipt_eligible(f, r, ib, fb))
        self.assertFalse(receipt_eligible(f, None, ib, fb))
        r['count_as_prospective'] = False
        self.assertFalse(receipt_eligible(f, r, ib, fb))
        self.assertEqual(f, original)

    def test_late_or_wrong_branch_receipt_never_becomes_prospective(self):
        f, r, ib, fb = self.frozen()
        r['checked_at'] = '2026-10-21T16:35:00+09:00'
        r['github_server_date'] = 'Wed, 21 Oct 2026 07:35:00 GMT'
        self.assertFalse(receipt_eligible(f, r, ib, fb))
        r['checked_at'] = '2026-10-21T16:30:00+09:00'
        r['github_server_date'] = 'Wed, 21 Oct 2026 07:30:00 GMT'
        r['remote_ref'] = 'main'
        self.assertFalse(receipt_eligible(f, r, ib, fb))

    def test_receipt_cannot_precede_generation_or_use_stale_server_time(self):
        f, r, ib, fb = self.frozen()
        r['github_server_date'] = 'Wed, 21 Oct 2026 07:10:00 GMT'
        self.assertFalse(receipt_eligible(f, r, ib, fb))
        r['github_server_date'] = 'Wed, 21 Oct 2026 07:28:00 GMT'
        self.assertFalse(receipt_eligible(f, r, ib, fb))

    def test_input_or_forecast_tampering_rejected(self):
        f, r, ib, fb = self.frozen()
        with self.assertRaisesRegex(ValueError, 'content identity'):
            receipt_eligible(f, r, ib, fb + b' ')
        snap = json.loads(ib); snap['boats'][0]['avg_st'] = .01
        with self.assertRaisesRegex(ValueError, 'input digest'):
            receipt_eligible(f, r, encode(snap), fb)

    def test_old_measurements_are_excluded_from_live_hypotheses(self):
        foot = load_foot(self.root, snapshot(), mode='live', at='2026-10-21T16:20:00+09:00')
        self.assertEqual(foot['status'], 'stale_excluded')

    def test_contradicted_attack_origin_is_not_preferred(self):
        f, _, _, _ = self.frozen()
        six = f['all_six'][5]
        for h in six['hypotheses']:
            h['conditions'] = [{'support': True}, {'support': False}]
            h['supported_observations'] = 1
        enrich(f, snapshot(), self.materials, root=self.root)
        self.assertIsNone(six['strongest_observed_hypothesis'])
        self.assertTrue(all(h['observation_status'] == 'contradicted_by_observation' for h in six['hypotheses']))

    def test_all_twenty_follower_pairs_and_sparse_sample_gate(self):
        f, _, _, _ = self.frozen()
        class Associations:
            def follower_counts(self, venue, course, method):
                return 29, {(2, 3): 12}
        enrich(f, snapshot(), Associations(), root=self.root)
        self.assertEqual(len(f['model_cards']['profiles_contextual_followers']), 10)
        self.assertEqual(f['contextual_policy']['evidence'], {})
        for b in f['all_six']:
            for h in b['hypotheses']:
                self.assertEqual(len(h['historical_follower_associations']), 20)
                self.assertTrue(all(not p['eligible_for_research_order'] for p in h['historical_follower_associations']))

    def test_latest_capture_is_one_race_and_refund_is_excluded(self):
        values = {'hit': True, 'stake_yen': 1000, 'return_yen': 2000}
        rows = [{'status': 'graded_prospective', 'count_as_prospective': True,
                 'race_id': 'r', 'key': 'T10', 'assembled_at': '2026-10-21T16:26:00+09:00', 'models': {'m': values}},
                {'status': 'graded_prospective', 'count_as_prospective': True,
                 'race_id': 'r', 'key': 'T4', 'assembled_at': '2026-10-21T16:32:00+09:00', 'models': {'m': values}},
                {'status': 'excluded', 'count_as_prospective': False, 'race_id': 'accident'}]
        report = summarize(rows)
        self.assertEqual(report['prospective_unique_races'], 1)
        self.assertEqual(report['selected_keys']['r'], 'T4')
        self.assertEqual(report['models']['m']['stake_yen'], 1000)

    def test_refuse_main_branch_before_any_git_mutation(self):
        with patch('research.materials_application_v1.live.git', return_value=b'main\n') as g:
            with self.assertRaisesRegex(ValueError, 'outside isolated'):
                publish(Store(self.root))
            self.assertEqual(g.call_count, 1)

    def test_old_remote_head_and_stale_server_ack_rejected(self):
        def response(sha, date):
            r = BytesIO(json.dumps({'object': {'sha': sha}}).encode()); r.headers = {'Date': date}; return r
        with patch('research.materials_application_v1.live.now', return_value=datetime(2026, 10, 21, 16, 30, tzinfo=JST)):
            with self.assertRaisesRegex(ValueError, 'acknowledgement missing'):
                remote_ack('a'*40, opener=lambda *a, **k: response('b'*40, 'Wed, 21 Oct 2026 07:30:00 GMT'))
            with self.assertRaisesRegex(ValueError, 'Stale'):
                remote_ack('a'*40, opener=lambda *a, **k: response('a'*40, 'Wed, 21 Oct 2026 07:20:00 GMT'))

    def test_first_day_without_verified_preinspection_holds(self):
        snap = snapshot(); snap['meta']['jcd'] = '06'
        store = Store(self.root)
        with patch.object(store, 'get', return_value={'status': 'unavailable'}):
            with self.assertRaisesRegex(ValueError, 'preinspection source unavailable'):
                preinspection(store, self.root / 'existing', snap)

    def test_tide_proxy_never_becomes_a_current_velocity_or_venue_measurement(self):
        snap = snapshot(); snap['meta']['jcd'] = '06'
        folder = self.root / 'tide_predictions'; folder.mkdir()
        heights = [20] * 24; heights[17] = 40
        raw = ''.join(f'{h:3d}' for h in heights) + '261021MI' + '9999999' * 8
        self.assertEqual(len(raw), 136)
        acquisition = Store(self.root).document(raw, {'retrieved_at': '2026-10-20T12:00:00+09:00',
            'url': 'https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/2026/MI.txt'})
        value = {'acquisition': acquisition, 'hourly': []}
        (folder / 'MI_2026.json').write_bytes(encode(value))
        row = tide_context(self.root, snap, '2026-10-21T16:30:00+09:00')
        self.assertEqual(row['height_cm_interpolated'], 32)
        self.assertFalse(row['current_velocity_known']); self.assertFalse(row['race_surface_measured'])
        value['acquisition']['retrieved_at'] = '2026-10-22T12:00:00+09:00'
        (folder / 'MI_2026.json').write_bytes(encode(value))
        self.assertEqual(tide_context(self.root, snap, '2026-10-21T16:30:00+09:00')['status'], 'excluded')


class PreparedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = PreparedMaterials(at='2026-10-21T08:00:00+09:00')

    def test_actual_acquired_feature_counts_and_periods_preserved(self):
        self.assertEqual(len(self.data.context_rows), 68808)
        self.assertEqual(len(self.data.motor_periods), 434)
        self.assertEqual(len(self.data.pairs), 1090)
        self.assertFalse(self.data.sources['compiled_seed']['historical_prospective_receipts'])
        self.assertGreater(self.data.profile('3783', 1, '20261021')['denominator'], 0)

    def test_prepared_history_cannot_predict_own_period(self):
        with self.assertRaisesRegex(ValueError, 'own or earlier'):
            self.data.profile('3783', 1, '20261017')

    def test_never_open_current_day_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'results'; p.mkdir()
            (p / '20261021_23_12.json').write_text('INVALID JSON; must never open')
            data = PreparedMaterials(at='2026-10-21T08:00:00+09:00', results_root=tmp)
            self.assertEqual(data.updates, [])

    def test_compiled_source_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p / 'seed_manifest.json').write_bytes(SEED.with_name('seed_manifest.json').read_bytes())
            (p / SEED.name).write_bytes(SEED.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                PreparedMaterials(p / SEED.name, at='2026-10-21T08:00:00+09:00')


if __name__ == '__main__':
    unittest.main()
