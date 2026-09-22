from copy import deepcopy
from datetime import datetime
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import four_way_prototype as trial
import hiyori_model
import prototype_runner as runner
from test_hiyori_parallel import fixtures


def prepared():
    official, source, request = fixtures()
    for row in official['trifecta']:
        row['odds'] = 20.0
    source['fetched_at'] = '2026-09-21T10:16:00+09:00'
    hiyori = hiyori_model.analyze(official, source, '20260921', '05', 1)
    now = datetime.fromisoformat('2026-09-21T10:17:00+09:00')
    return request, hiyori, source, now


class ModelTests(unittest.TestCase):
    def test_weights_are_opposite_and_normalized(self):
        a = [{'combination': c, 'probability': 20.0 if c.startswith('1-') else 1.0}
             for c in sorted(trial.COMBINATIONS)]
        b = [{'combination': c, 'probability': 20.0 if c.startswith('4-') else 1.0}
             for c in sorted(trial.COMBINATIONS)]
        first = trial.fuse(a, b, .7, .3)
        second = trial.fuse(a, b, .3, .7)
        self.assertTrue(first[0]['combination'].startswith('1-'))
        self.assertTrue(second[0]['combination'].startswith('4-'))
        self.assertAlmostEqual(sum(x['probability'] for x in first), 1)
        da, db = trial.distribution(a), trial.distribution(b)
        self.assertAlmostEqual(first[0]['probability'], .7*da[first[0]['combination']]+.3*db[first[0]['combination']])
        self.assertEqual(first, trial.fuse(list(reversed(a)), b, .7, .3))

    def test_invalid_or_incomplete_distributions_are_rejected(self):
        rows = [{'combination': c, 'probability': 1} for c in sorted(trial.COMBINATIONS)]
        for bad in (rows[:-1], rows+[rows[0]], [dict(rows[0], probability=float('nan'))]+rows[1:],
                    [dict(rows[0], probability=-1)]+rows[1:]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                trial.fuse(rows, bad)
        with self.assertRaises(ValueError):
            trial.fuse(rows, rows, .7, .7)

    def test_five_cards_keep_legacy_budget_and_p3_structure(self):
        req, hy, src, now = prepared()
        original = deepcopy((req, hy, src))
        record = trial.build_bundle(req, hy, src, now)
        self.assertEqual((req, hy, src), original)
        self.assertEqual(set(record['models']), set(trial.STREAMS))
        for stream in ('existing', 'hiyori', 'prototype1', 'prototype2'):
            card = record['models'][stream]
            self.assertEqual(len(set(card['picks'])), 10)
            self.assertEqual(card['stake_yen'], 1000)
            self.assertTrue(card['odds_complete'])
            self.assertEqual({r['odds'] for r in card['trifecta']}, {20.0})
            self.assertAlmostEqual(sum(r['probability'] for r in card['trifecta']), 1)
        p3 = record['models']['prototype3']
        self.assertGreaterEqual(p3['point_count'], 1)
        self.assertLessEqual(p3['point_count'], 16)
        self.assertEqual(p3['main_picks'], record['native_candidate_picks']['hiyori'][:16])
        self.assertFalse(set(p3['main_picks']) & set(p3['cover_picks']))
        self.assertEqual(p3['picks'], p3['main_picks'] + p3['cover_picks'])
        self.assertEqual(p3['stake_yen'], 100 * p3['point_count'])
        self.assertTrue(p3['odds_complete'])
        self.assertEqual(record['models']['prototype1']['weights'], {'hiyori_main': 1.0, 'mid_cover_policy': 1.0})
        self.assertEqual(record['models']['prototype2']['weights'], {'hiyori_main': 1.0, 'mid_cover_policy': 1.0})
        self.assertEqual(len(record['models']['prototype1']['main_picks']), 4)
        self.assertEqual(len(record['models']['prototype1']['cover_picks']), 6)
        self.assertEqual(len(record['models']['prototype2']['main_picks']), 6)
        self.assertEqual(len(record['models']['prototype2']['cover_picks']), 4)
        self.assertEqual(record['models']['prototype1']['main_picks'], record['native_candidate_picks']['hiyori'][:4])
        self.assertEqual(record['models']['prototype2']['main_picks'], record['native_candidate_picks']['hiyori'][:6])

    def test_even_three_way_tie_has_ten_points(self):
        req, hy, src, now = prepared()
        for analysis in (req['official'], hy):
            for row in analysis['trifecta']:
                row['probability'] = 1/120
        record = trial.build_bundle(req, hy, src, now)
        for stream in ('existing', 'hiyori', 'prototype1', 'prototype2'):
            self.assertEqual(len(record['models'][stream]['picks']), 10)
        self.assertLessEqual(len(record['models']['prototype3']['picks']), 16)

    def test_missing_odds_are_unknown_not_zero(self):
        req, hy, src, now = prepared()
        for row in req['official']['trifecta']:
            row.pop('odds')
        record = trial.build_bundle(req, hy, src, now)
        for card in record['models'].values():
            self.assertFalse(card['odds_complete'])
            self.assertIsNone(card['estimated_return_yen'])

    def test_deadline_sources_and_entrants_are_checked(self):
        req, hy, src, now = prepared()
        with self.assertRaises(ValueError):
            trial.build_bundle(req, hy, src, datetime.fromisoformat('2026-09-21T10:30:01+09:00'))
        with self.assertRaises(ValueError):
            trial.build_bundle(req, hy, dict(src, fetched_at='2026-09-21T10:18:00+09:00'), now)
        wrong = deepcopy(hy)
        wrong['inputs'][0]['racer_id'] = '9999'
        with self.assertRaises(ValueError):
            trial.build_bundle(req, wrong, src, now)
        wrong = deepcopy(hy)
        wrong['features'] = []
        with self.assertRaises(ValueError):
            trial.build_bundle(req, wrong, src, now)
        req['official']['preview']['exhibition_count'] = 5
        with self.assertRaises(ValueError):
            trial.build_bundle(req, hy, src, now)


class StorageAndSettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patched = patch.object(trial, 'ROOT', Path(self.tmp.name))
        patched.start()
        self.addCleanup(patched.stop)

    def record(self):
        req, hy, src, now = prepared()
        record = trial.build_bundle(req, hy, src, now)
        trial.persist(record, req, src, hy)
        return record

    def test_first_snapshot_is_immutable(self):
        req, hy, src, now = prepared()
        record = trial.build_bundle(req, hy, src, now)
        trial.persist(record, req, src, hy)
        changed = deepcopy(record)
        changed['models']['prototype1']['picks'] = ['6-5-4']
        stored = trial.persist(changed, req, src, hy)
        self.assertEqual(stored, record)
        with gzip.open(trial.ROOT/'20260921/snapshots/20260921_05_01.json.gz', 'rt') as handle:
            self.assertEqual(json.load(handle)['record_digest'], record['digest'])

    def test_pending_is_not_a_loss_and_cash_uses_actual_payout(self):
        record = self.record()
        self.assertIsNone(trial.evaluate(record, {'status': 'pending'}))
        report = trial.summarize('20260921')
        self.assertEqual(report['pending'], 1)
        self.assertIsNone(report['totals']['existing']['hit_rate'])
        winner = record['models']['hiyori']['picks'][0]
        result = trial.evaluate(record, {'status': 'settled', 'payouts': {winner: 11810}, 'refund_lanes': []})
        self.assertTrue(result['models']['hiyori']['manshu'])
        self.assertEqual(result['models']['hiyori']['return_yen'], 11810)
        trial.write_json(trial.ROOT/'20260921/results'/f"{record['key']}.json", result)
        report = trial.summarize('20260921')
        self.assertEqual({r['judged'] for r in report['totals'].values()}, {1})
        self.assertEqual(report['pending'], 0)
        self.assertEqual(report['pairs']['existing_vs_hiyori']['both']+
                         len(report['pairs']['existing_vs_hiyori']['a_only'])+
                         len(report['pairs']['existing_vs_hiyori']['b_only'])+
                         report['pairs']['existing_vs_hiyori']['neither'], 1)

    def test_refunds_and_void_do_not_fake_hits_or_shared_samples(self):
        record = self.record()
        void = trial.evaluate(record, {'status': 'void', 'payouts': {}, 'refund_lanes': []})
        self.assertFalse(void['comparable'])
        self.assertTrue(all(m['return_yen'] == m['stake_yen'] and not m['hit'] for m in void['models'].values()))
        special = trial.evaluate(record, {'status': 'special', 'payouts': {}, 'special_per_100': 70})
        self.assertTrue(all(m['return_yen'] == 70 * len(record['models'][stream]['picks'])
                            for stream, m in special['models'].items()))
        # Full refund for one strategy means this race is outside the shared cohort.
        record['models']['existing']['picks'] = [c for c in sorted(trial.COMBINATIONS) if c.startswith('1-')][:10]
        partial = trial.evaluate(record, {'status': 'settled', 'payouts': {'4-5-6': 5000}, 'refund_lanes': [1]})
        self.assertFalse(partial['comparable'])
        self.assertEqual(partial['models']['existing']['refund_yen'], 1000)

    def test_all_dead_heated_winners_are_paid(self):
        record = self.record()
        winners = record['models']['hiyori']['picks'][:2]
        result = trial.evaluate(record, {'status': 'settled', 'payouts': {winners[0]: 300, winners[1]: 400}, 'refund_lanes': []})
        self.assertEqual(result['models']['hiyori']['return_yen'], 700)
        self.assertTrue(result['models']['hiyori']['torigami'])

    def test_late_fetch_is_rejected_before_persistence(self):
        req, hy, src, now = prepared()
        clock = iter([now, datetime.fromisoformat('2026-09-21T10:29:30+09:00'),
                      datetime.fromisoformat('2026-09-21T10:29:31+09:00')])
        with patch.object(runner.base, 'analyze_official', return_value=req['official']), \
             patch.object(runner.hiyori_source, 'fetch_race', return_value=src), \
             patch.object(runner.hiyori_model, 'analyze', return_value=hy), \
             patch.object(trial, 'persist') as writer:
            state = runner.collect_race('20260921', '05', 1, '10:30', lambda: next(clock))
        self.assertEqual(state, 'missed_deadline')
        writer.assert_not_called()

    def test_source_failure_never_creates_five_baseline_copies(self):
        req, hy, src, now = prepared()
        with patch.object(runner.base, 'analyze_official', return_value=req['official']), \
             patch.object(runner.hiyori_source, 'fetch_race', side_effect=ValueError), \
             patch.object(trial, 'persist') as writer:
            state = runner.collect_race('20260921', '05', 1, '10:30', lambda: now)
        self.assertEqual(state, 'data_error')
        writer.assert_not_called()

    def test_recorded_race_is_not_refetched(self):
        self.record()
        with patch.object(runner.base, 'analyze_official') as fetch:
            state = runner.collect_race('20260921', '05', 1, '10:30')
        self.assertEqual(state, 'recorded')
        fetch.assert_not_called()

    def test_coverage_distinguishes_trial_start_and_missed_race(self):
        report = runner.coverage('20260921', {'05': ['10:00', '10:30', '11:00']}, {},
                                 datetime.fromisoformat('2026-09-21T10:40:00+09:00'),
                                 '2026-09-21T10:10:00+09:00')
        self.assertEqual(report['counts'], {'closed_before_trial_start': 1, 'missed_deadline': 1, 'scheduled': 1})

    def test_first_pass_fetches_schedule_even_on_a_fresh_runner(self):
        now = datetime.fromisoformat('2026-09-21T10:00:00+09:00')
        with patch.object(runner.time, 'monotonic', return_value=0), \
             patch.object(runner, 'now_jst', return_value=now), \
             patch.object(runner.base, 'discover_venues', return_value=['05']) as discover, \
             patch.object(runner, 'get_schedule', return_value=('05', ['11:00'], None)), \
             patch.object(runner, 'settle_available') as settle:
            self.assertEqual(runner.run(0), 0)
        discover.assert_called_once_with('20260921')
        settle.assert_called_once()
        report = trial.read(trial.ROOT/'20260921/coverage.json')
        self.assertEqual(report['expected'], 1)
        self.assertEqual(report['counts'], {'scheduled': 1})


if __name__ == '__main__':
    unittest.main()
