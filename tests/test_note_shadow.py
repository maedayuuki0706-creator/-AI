import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from research import note_shadow as m

class ShadowTest(unittest.TestCase):
    def test_distribution_checks(self):
        rows = [{'combination': c, 'probability': 1/120} for c in sorted(m.TICKETS)]
        self.assertEqual(len(m.probs(rows)), 120)
        with self.assertRaises(ValueError): m.probs(rows[:-1])
        rows[0]['probability'] = -1
        with self.assertRaises(ValueError): m.probs(rows)

    def test_temporal_split_and_missing_odds(self):
        d = {c: 1/120 for c in m.TICKETS}
        history = [{'day': '20261011', 'winner': '1-2-3', 'probabilities': d} for _ in range(2)]
        self.assertEqual(m.choose_exponent(history, '20261012', min_train=3), (1.0, 2, False))
        history.append({'day': '20261012', 'winner': '1-2-3', 'probabilities': d})
        self.assertEqual(m.choose_exponent(history, '20261012', min_train=3), (1.0, 2, False))
        self.assertEqual(m.select(d, {})['ev_10'], [])
        self.assertEqual(m.select(d, {})['ev_gate_85'], [])

    def test_replay_and_roi(self):
        p = {c: 1/120 for c in m.TICKETS}
        p['1-2-3'] *= 2
        total = sum(p.values())
        p = {c: v/total for c, v in p.items()}
        sample = {'model': 'pt2', 'version': 'v2', 'probabilities': p,
                  'odds': {c: 200 for c in m.TICKETS}, 'winner': '1-2-3',
                  'payout_yen': 5000, 'native_picks': ['1-2-3']}
        rows = m.replay([dict(sample, day='20261011', key='20261011_01_01'),
                         dict(sample, day='20261012', key='20261012_01_01')], min_train=1)
        self.assertFalse(rows[0]['calibration_fitted'])
        self.assertTrue(rows[1]['calibration_fitted'])
        self.assertEqual(rows[1]['training_prior_races'], 1)
        self.assertEqual(rows[0]['strategies']['raw_prob_10']['stake_yen'], 1000)
        self.assertEqual(rows[0]['strategies']['raw_prob_10']['return_yen'], 5000)
        self.assertEqual(rows[0]['strategies']['native_logged']['stake_yen'], 100)
        self.assertEqual(m.summarize(rows, {})['valid_model_races'], 2)

    def test_delivery_receipt_is_required_and_does_not_write_sources(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred = root/'data/prototype3_delivery/predictions/20261012_01_01.json'
            receipt = root/'data/prototype3_delivery/deliveries/20261012_01_01.json'
            official = root/'data/prototype_scoreboard/20261012/official/20261012_01_01.json'
            for p in (pred, receipt, official): p.parent.mkdir(parents=True, exist_ok=True)
            raw = {'day':'20261012','deadline':'12:00','created_at':'2026-10-12T11:00:00+09:00',
                   'key':'20261012_01_01','digest':'abc','model':{'trifecta':[
                     {'combination':c,'probability':1/120,'odds':100} for c in sorted(m.TICKETS)]}}
            pred.write_text(json.dumps(raw))
            receipt.write_text(json.dumps({'key':raw['key'],'prediction_digest':'abc',
                                             'delivered_at':'2026-10-12T11:02:00+09:00'}))
            official.write_text(json.dumps({'status':'settled','payouts':{'1-2-3':12000},'refund_lanes':[]}))
            self.assertEqual(len(m.load_samples(root)[0]), 1)
            receipt.write_text(json.dumps({'key':raw['key'],'prediction_digest':'WRONG',
                                             'delivered_at':'2026-10-12T11:02:00+09:00'}))
            samples, excluded = m.load_samples(root)
            self.assertFalse(samples)
            self.assertEqual(excluded['missing_matching_receipt'], 1)

if __name__ == '__main__':
    unittest.main()
