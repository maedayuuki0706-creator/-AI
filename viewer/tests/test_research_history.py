import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import gzip

spec=importlib.util.spec_from_file_location('builder',Path(__file__).parents[1]/'build_research_history.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class BuilderTests(unittest.TestCase):
    def source(self, root, rows, day='20261001'):
        folder=root/'data/official_results';folder.mkdir(parents=True,exist_ok=True)
        (folder/(day+'.json')).write_text(json.dumps(rows))
    def test_invalid_and_nonsettled(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);out=root/'out'
            self.source(root,{'03:1':{'status':'settled','payouts':{'1-2-3':100}},'03:2':{'status':'pending','payouts':{}},'03:3':{'status':'settled','payouts':{'1-1-2':100}},'03:4':{'status':'settled','payouts':{'1-2-3':True}}})
            report=b.build(root,None,out);self.assertEqual(report['indexed'],1);self.assertEqual(sum(report['exclusions'].values()),3)
    def test_conflict_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);out=root/'out'
            self.source(root,{'03:1':{'status':'settled','payouts':{'1-2-3':200}},'03:2':{'status':'settled','payouts':{'1-2-3':100}}})
            audit=root/'audit.gz';audit.write_bytes(gzip.compress(json.dumps([{'date':'2026-10-01','venue_code':'03','race_no':1,'official_verified':True,'official_trifectas':[{'combination':'1-2-3','payout_per_100':100}]}]).encode()))
            report=b.build(root,audit,out);self.assertEqual(report['indexed'],1);self.assertEqual(report['conflict_races'],[['20261001','03',1]])
    def test_idempotent_and_failure_preserves_manifest(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);out=root/'out';self.source(root,{'03:1':{'status':'settled','payouts':{'1-2-3':100}}})
            b.build(root,None,out);first={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*.json')}
            b.build(root,None,out);self.assertEqual(first,{str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*.json')})
            (root/'data/official_results/20261002.json').write_text('{bad')
            with self.assertRaises(ValueError):b.build(root,None,out)
            self.assertEqual(first,{str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*.json')})
    def test_calendar_identity(self):
        self.assertIsNone(b.identity('20260230','03',1));self.assertIsNone(b.identity('20261001','25',1));self.assertIsNone(b.identity('20261001','03',13))

if __name__=='__main__':unittest.main()
