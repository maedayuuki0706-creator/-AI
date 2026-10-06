from datetime import datetime
import unittest

import four_way_prototype as trial
import hiyori_model
import prototype12_delivery as delivery
from test_hiyori_parallel import fixtures


class NewPrototypeFusionTests(unittest.TestCase):
    def prepared(self):
        official, source, request = fixtures()
        for row in official['trifecta']:
            row['odds'] = 80.0
        source['fetched_at'] = '2026-09-21T10:16:00+09:00'
        hiyori = hiyori_model.analyze(official, source, '20260921', '05', 1)
        now = datetime.fromisoformat('2026-09-21T10:17:00+09:00')
        return request, hiyori, source, now

    def test_pt3_is_unchanged_control_and_new_models_are_distinct(self):
        req, hy, src, now = self.prepared()
        record = trial.build_bundle(req, hy, src, now)
        p1 = record['models']['prototype1']
        p2 = record['models']['prototype2']
        p3 = record['models']['prototype3']

        self.assertEqual(p3['selection_policy'], 'hiyori-native-main-plus-mid-on-hiyori-cover-cap16')
        self.assertEqual(p3['main_picks'], record['native_candidate_picks']['hiyori'][:16])
        self.assertEqual(p1['selection_policy'], 'scent-box-exhibition-fusion-v1')
        self.assertEqual(len(p1['box_lanes']), 3)
        self.assertEqual(len(p1['box_picks']), 6)
        self.assertEqual(len(p1['cover_picks']), 2 if not p1['cover_formation'] else 4)
        self.assertLessEqual(len(p1['longshot_picks']), 3)
        self.assertEqual(len(set(p1['picks'])), p1['point_count'])
        self.assertGreaterEqual(p1['point_count'], 8)
        self.assertLessEqual(p1['point_count'], 13)
        message = delivery.model_message(record, 'prototype1')
        self.assertIn('ここが匂う！', message)
        self.assertIn('📦 **BOX', message)
        self.assertIn('🛟 **抜け目', message)
        self.assertIn('💣 **穴目', message)
        self.assertIn('試験配信', message)
        self.assertEqual(p2['selection_policy'], 'pt3-db-consensus-no-fixed-point-cap')
        self.assertGreaterEqual(p2['point_count'], p3['point_count'])
        self.assertIsNone(p2['structure']['fixed_point_cap'])
        self.assertTrue(set(p3['picks']).issubset(set(p2['picks'])))
        self.assertTrue(set(record['native_candidate_picks']['prototype2_existing_db'])
                        <= set(p2['picks']))

    def test_pt2_retains_uncapped_candidates(self):
        req, hy, src, now = self.prepared()
        record = trial.build_bundle(req, hy, src, now)
        p2 = record['models']['prototype2']
        p3 = record['models']['prototype3']
        self.assertIsNone(p2['structure']['fixed_point_cap'])
        self.assertGreaterEqual(p2['point_count'], p3['point_count'])
        self.assertTrue(set(record['native_candidate_picks']['prototype2_existing_db'])
                        <= set(p2['picks']))

    def test_box_hit_is_measured_separately_from_cover_hit(self):
        req, hy, src, now = self.prepared()
        record = trial.build_bundle(req, hy, src, now)
        box = record['models']['prototype1']['box_picks'][0]
        cover = record['models']['prototype1']['cover_picks'][0]
        hit = trial.evaluate(record, {'status': 'settled', 'payouts': {box: 1000}})
        self.assertTrue(hit['models']['prototype1']['box_hit'])
        cover_hit = trial.evaluate(record, {'status': 'settled', 'payouts': {cover: 1000}})
        self.assertTrue(cover_hit['models']['prototype1']['hit'])
        self.assertFalse(cover_hit['models']['prototype1']['box_hit'])


if __name__ == '__main__':
    unittest.main()
