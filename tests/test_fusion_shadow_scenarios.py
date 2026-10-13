from copy import deepcopy
from datetime import timedelta
import unittest

from tests.test_fusion_shadow import fixture, record, result, NOW
import fusion_shadow as core


class ProspectiveScenarioTests(unittest.TestCase):
    def test_every_boat_and_every_ticket_has_a_prospective_reason(self):
        prediction = record()
        self.assertEqual([s['lane'] for s in prediction['boat_scenarios']], list(range(1, 7)))
        self.assertAlmostEqual(sum(prediction['head_probabilities'].values()), 1)
        self.assertEqual(set(prediction['ticket_reasons']), set(prediction['models']['fusion']['picks']))
        for s in prediction['boat_scenarios']:
            self.assertTrue(s['win_paths'] and s['win_conditions'] and s['loss_paths'] and s['axis_reason'])
        for r in prediction['ticket_reasons'].values():
            self.assertLessEqual(r['second_given_head'], 1)
            self.assertLessEqual(r['third_given_head_second'], 1)

    def test_missing_measurements_are_not_replaced_by_defaults(self):
        request, analyses, strategies = fixture()
        for a in analyses.values():
            for b in a['inputs']:
                for k in ('avg_st', 'exhibition_st', 'motor_top2_rate', 'win_rate'):
                    b.pop(k, None)
        p = core.build_prediction(request, analyses, strategies, NOW)
        for s in p['boat_scenarios']:
            self.assertIsNone(s['evidence']['average_st'])
            self.assertIsNone(s['evidence']['motor_top2_rate'])
            self.assertIn('average_st', s['missing_fields'])
            self.assertFalse(s['factor_components'])

    def test_exhibition_flying_does_not_become_a_fast_actual_start(self):
        request, analyses, strategies = fixture()
        b = analyses['existing']['inputs'][3]
        b['exhibition_st'] = 0.01
        b['exhibition_st_timing'] = -0.1
        p = core.build_prediction(request, analyses, strategies, NOW)
        s = p['boat_scenarios'][3]
        self.assertFalse(any(c['field']=='exhibition_st_vs_inside' for c in s['factor_components']))
        self.assertTrue(any('展示F' in n for n in s['evidence_notes']))

    def test_real_st_advantage_changes_the_research_head_probability(self):
        request, analyses, strategies = fixture()
        before = core.build_prediction(request, analyses, strategies, NOW)
        analyses['existing']['inputs'][3]['avg_st'] = .06
        after = core.build_prediction(request, analyses, strategies, NOW)
        self.assertGreater(after['head_probabilities']['4'], before['head_probabilities']['4'])
        self.assertFalse(after['probabilities_are_calibrated'])

    def test_entry_change_compares_neighbors_by_course_not_boat_number(self):
        request, analyses, strategies = fixture()
        analyses['existing']['inputs'][4]['predicted_course'] = 2
        analyses['existing']['inputs'][1]['predicted_course'] = 5
        p = core.build_prediction(request, analyses, strategies, NOW)
        self.assertEqual(p['boat_scenarios'][2]['inside_lane'], 5)
        self.assertEqual(p['boat_scenarios'][4]['anticipated_methods'], ['差し','まくり'])

    def test_result_missing_actual_st_remains_unknown(self):
        p = record()
        o = core.evaluate(p, result(p), NOW+timedelta(minutes=20))
        self.assertTrue(all(x['actual_st'] is None for x in o['scenario_review']['boats']))
        self.assertTrue(all(x['method_matches_win_hypothesis'] is None for x in o['scenario_review']['boats']))
        self.assertTrue(all(x['causal_attribution']=='unverified_without_race_video' for x in o['scenario_review']['boats']))
        self.assertIsNone(o['scenario_review']['abnormal_race_detected'])
        self.assertFalse(o['scenario_review']['ordinary_scenario_learning_eligible'])

    def test_accidents_are_not_learned_as_ordinary_scenario_losses(self):
        p=record();r=result(p)
        r['race_details']={'method':'恵まれ','finish':[{'lane':1,'status':'finished','st':.1,'course':1},
                                                   {'lane':2,'status':'F','st':None,'course':2}]}
        review=core.evaluate(p,r,NOW+timedelta(minutes=20))['scenario_review']
        self.assertTrue(review['abnormal_race_detected'])
        self.assertFalse(review['ordinary_scenario_learning_eligible'])
        self.assertTrue(all(x['method_matches_win_hypothesis'] is None for x in review['boats']))


if __name__ == '__main__':
    unittest.main()
