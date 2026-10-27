from datetime import timedelta
import unittest

from tests.test_fusion_shadow import record, result, NOW
import fusion_shadow as core
import sync_fusion_shadow_sheet as sheet


class FrozenSheetTests(unittest.TestCase):
    def test_old_reference_preserved_new_version_is_separate_and_replay_is_empty(self):
        p = record()
        legacy = ['2026-10-12','浜名湖','1R',p['key'],'旧版参考']+['old']*14
        race_row, boat_rows = sheet.rows_for(p)
        req, stats = sheet.make_plan([(p,None)], [legacy], [], 10, 11)
        self.assertEqual(stats['new_races'],1)
        self.assertEqual(stats['new_boats'],6)
        self.assertNotEqual(race_row[3], legacy[3])
        self.assertTrue(all(r.get('updateCells',{}).get('range',{}).get('startRowIndex',999)>=4
                            for r in req if r.get('updateCells',{}).get('range',{}).get('sheetId')==10))
        req, stats = sheet.make_plan([(p,None)], [legacy,race_row], boat_rows, 10, 11)
        self.assertEqual(req,[])
        self.assertEqual(stats['new_races'],0)

    def test_result_updates_only_review_columns_and_keeps_forecast_frozen(self):
        p = record();race,boats=sheet.rows_for(p)
        outcome = core.evaluate(p,result(p),NOW+timedelta(minutes=20))
        req,stats=sheet.make_plan([(p,outcome)],[race],boats,10,11)
        self.assertEqual(stats['new_races'],0)
        self.assertTrue(req)
        for r in req:
            self.assertEqual(r['updateCells']['range']['startColumnIndex'],16)

    def test_changed_inputs_and_duplicate_ids_stop_without_any_write_plan(self):
        p=record();race,boats=sheet.rows_for(p)
        changed=list(race);changed[6]='6-5-4'
        with self.assertRaises(ValueError):sheet.make_plan([(p,None)],[changed],boats,10,11)
        with self.assertRaises(ValueError):sheet.make_plan([(p,None)],[race,race],boats,10,11)

    def test_capacity_never_silently_writes_outside_filter_bounds(self):
        p=record()
        with self.assertRaises(ValueError):sheet.make_plan([(p,None)],[],[],10,11,race_capacity=3)


if __name__ == '__main__':
    unittest.main()
