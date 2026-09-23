from datetime import datetime
import unittest

import four_way_prototype as trial
import hiyori_model
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
        self.assertEqual(p1['selection_policy'], 'pt3-core-10-plus-longshot-sniper-max3')
        self.assertGreaterEqual(p1['point_count'], 1)
        self.assertLessEqual(p1['point_count'], 13)
        self.assertEqual(p2['selection_policy'], 'pt3-existing-consensus-compress-grade-7-8-10')
        self.assertGreaterEqual(p2['point_count'], 1)
        self.assertLessEqual(p2['point_count'], 10)
        self.assertTrue(set(p2['picks']).issubset(set(p3['picks'])))

    def test_pt2_grade_targets_are_compact(self):
        req, hy, src, now = self.prepared()
        record = trial.build_bundle(req, hy, src, now)
        p2 = record['models']['prototype2']
        expected = {'A': 7, 'B': 8, 'C': 10}[p2['grade']]
        self.assertEqual(p2['point_count'], min(expected, record['models']['prototype3']['point_count']))


if __name__ == '__main__':
    unittest.main()
