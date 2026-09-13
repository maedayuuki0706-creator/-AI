import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import direct_discord_notify as n
from race_context import previous_form, parse_result
from prediction_engine import score_boat
from daily_learning import aggregate, evaluate_prediction, parse_finish_order

FIXTURES=Path(__file__).parent/'fixtures'

class DeliveryTests(unittest.TestCase):
    def setUp(self): self.policy=n.load_policy()
    def test_all_12_tokoname_preliminary_only_on_requested_day(self):
        now=datetime(2026,9,13,8,15,tzinfo=n.JST)
        for race in range(1,13):
            self.assertEqual(n.due_phase(self.policy,now,'08','10:43',set(),race),'preliminary')
        self.assertEqual(n.due_phase(self.policy,now,'24','10:43',set(),1),'preliminary')
        self.assertIsNone(n.due_phase(self.policy,now.replace(day=14),'08','10:43',set(),1))
    def test_delays_duplicates_and_closed_races(self):
        now=datetime(2026,9,13,10,30,tzinfo=n.JST)
        self.assertEqual(n.due_phase(self.policy,now,'08','10:43',set(),1),'final')
        self.assertIsNone(n.due_phase(self.policy,now,'08','10:43',{('20260913','08',1,'final')},1))
        self.assertIsNone(n.due_phase(self.policy,now,'08','10:34',set(),1))
        self.assertIsNone(n.due_phase(self.policy,now,'08','10:20',set(),1))
    def test_pending_exhibition_is_not_grade_c_or_ai_selected(self):
        analysis={'grade':None,'preview':{'exhibition_count':0},'trifecta':[]}
        self.assertFalse(n.selected_by_ai(analysis,self.policy))
    def test_ai_selection_requires_real_ev_and_weather(self):
        a={'grade':'B','preview':{'exhibition_count':6,'wind_speed':1,'wave_cm':1},'trifecta':[{'probability':.08,'expected_value':1.2}]}
        self.assertTrue(n.selected_by_ai(a,self.policy))
        a['trifecta'][0]['expected_value']=None
        self.assertFalse(n.selected_by_ai(a,self.policy))
    def test_six_racers_parse_despite_whitespace_and_prior_day_results(self):
        raw=(FIXTURES/'racelist-20260913-08-1.html').read_text()
        with patch.object(n,'fetch',return_value=raw): boats=n.parse_racelist_boats('20260913','08',1)
        self.assertEqual([b['racer_id'] for b in boats],['5129','5203','4941','5052','5436','5078'])
        self.assertEqual(boats[0]['name'],'山口真喜子')
        self.assertEqual(boats[0]['motor_top2_rate'],34.10)
    def test_real_exhibition_entry_and_f_are_parsed(self):
        preview=n.parse_beforeinfo((FIXTURES/'beforeinfo-20260912-08-3.html').read_text())
        self.assertEqual(preview['exhibition_count'],6)
        self.assertEqual(preview['boats'][5]['predicted_course'],4)
        self.assertTrue(preview['boats'][1]['exhibition_flying'])
        self.assertNotIn('exhibition_st',preview['boats'][1])
        pending=n.parse_beforeinfo((FIXTURES/'beforeinfo-20260913-08-1.html').read_text())
        self.assertEqual(pending['exhibition_count'],0)
    def test_unrecorded_average_st_does_not_shift_other_fields(self):
        raw=(FIXTURES/'racelist-20260913-08-1.html').read_text()
        with patch.object(n,'fetch',return_value=raw):
            original=n.parse_racelist_boats('20260913','08',1)
        import re
        changed=re.sub(r'(L0\s*<br\s*/?>\s*)(?:0\.\d+)', r'\1-', raw, count=1)
        self.assertNotEqual(raw, changed)
        with patch.object(n,'fetch',return_value=changed):
            boats=n.parse_racelist_boats('20260913','08',1)
        self.assertEqual(len(boats),6)
        self.assertIsNone(boats[0]['avg_st'])
        self.assertEqual(boats[0]['win_rate'],original[0]['win_rate'])
        self.assertEqual(boats[0]['motor_top2_rate'],original[0]['motor_top2_rate'])
    def test_previous_day_form_does_not_leak_same_day_or_other_venue(self):
        boats=[{'lane':5,'racer_id':'4208'}]
        self.assertGreater(previous_form('20260913','08',boats)[5]['score_delta'],0)
        self.assertEqual(previous_form('20260912','08',boats),{})
        self.assertEqual(previous_form('20260913','24',boats),{})
        self.assertEqual(previous_form('20260913','08',[{'lane':5,'racer_id':'9999'}]),{})
    def test_f_result_is_not_sixth_place(self):
        raw=(FIXTURES/'raceresult-20260912-08-10.html').read_text()
        result=parse_result(raw,'20260912','08',10)
        row=next(b for b in result['finish'] if b['racer_id']=='5357')
        self.assertIsNone(row['finish']);self.assertEqual(row['status'],'F')
        self.assertEqual(parse_finish_order(raw),[1,2,4])
    def test_percent_one_is_one_percent_and_exhibition_f_not_a_boost(self):
        boat={'lane':2,'win_rate':1,'top2_rate':1,'top3_rate':1}
        self.assertAlmostEqual(score_boat(boat,{})['components']['racer'],.0595,places=4)
        self.assertEqual(score_boat({**boat,'exhibition_st':-.1},{})['components']['start'],score_boat(boat,{})['components']['start'])
    def test_daily_accuracy_counts_only_displayed_and_one_sample_per_race(self):
        r={'day':'20260913','jcd':'08','rno':1,'main':['1-2-3'],'cover':['2-1-3'],'all_picks':['1-2-3','2-1-3','3-2-1']}
        self.assertFalse(evaluate_prediction(r,[3,2,1])['any_hit'])
        stats=aggregate([{**r,'phase':'preliminary','any_hit':True},{**r,'phase':'final','any_hit':False}])
        self.assertEqual(stats['samples'],1);self.assertEqual(stats['overall']['any_hits'],0)
    def test_log_phase_is_reloaded_for_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(n,'LOG_PATH',Path(tmp)/'log.jsonl'):
            n.log_prediction({'day':'20260913','jcd':'08','rno':1,'phase':'preliminary'})
            self.assertEqual(n.load_deliveries(),{('20260913','08',1,'preliminary')})

if __name__=='__main__':unittest.main()
