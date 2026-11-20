import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from exhibition_study import audit_splits,columns
from official_profiles import program
from tide_study import tide
from longitudinal import nearest
from test_analyst_context import race


class SourceTests(unittest.TestCase):
    def test_tide_uses_completed_hours_and_station(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'2026-TA.txt'
            p.write_text(''.join(f'{x:3}' for x in range(24))+'261114TA\n')
            prof={'tide_enabled':True,'provider':'jma','station_code':'TA'}
            self.assertEqual(tide(folder,prof,'20261114','10:59')[1:],(10,1,'上げ'))
            self.assertIsNone(tide(folder,prof,'20261114','00:05'))
            self.assertIsNone(tide(folder,dict(prof,tide_enabled=False),'20261114','10:59'))

    def test_original_schedule_exclusion(self):
        with tempfile.TemporaryDirectory() as folder:
            days=[{'day':'20261114','manifest_status':'complete','races':[{'venue':v,'race_no':1} for v in ('03','08')]}]
            totals,retry=audit_splits(Path(folder),days)
            self.assertNotIn('03',totals)
            self.assertEqual(retry,[('20261114','08',1,'no_daily_file')])

    def test_split_rejects_wrong_racer(self):
        boats=[{'name':f'選手{i}'} for i in range(1,7)]
        self.assertEqual(columns({},boats),{})

    def test_broader_similarity_never_uses_target_or_future(self):
        target=race('20261114')
        for b in target['rows']: b.update(current_class='A2',tilt=0.)
        past=dict(target,day='20261113',venue='08',race_no=1,method='逃げ')
        rr,n=nearest([past,dict(past,day='20261114')],target)
        self.assertEqual((rr[0][0],n),(0,1))
