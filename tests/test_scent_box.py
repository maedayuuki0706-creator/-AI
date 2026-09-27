from itertools import permutations
import unittest

import scent_box


def analysis(preferred=(1, 4, 5), st=None):
    st = st or {}
    rows = []
    for triple in permutations(range(1, 7), 3):
        combo = '-'.join(map(str, triple))
        weight = 8.0 if set(triple) == set(preferred) else 1.0
        rows.append({'combination': combo, 'probability': weight})
    return {
        'trifecta': rows,
        'inputs': [{'lane': n, 'exhibition_st': st.get(n)} for n in range(1, 7)],
        'preview': {'exhibition_count': 6},
        'race_shape': {'best_attack_lane': 4, 'best_attack_method': 'まくり差し'},
    }


class ScentBoxTests(unittest.TestCase):
    def test_box_cover_and_holes_do_not_overlap(self):
        base = analysis(st={1: .13, 2: .22, 3: .21, 4: .09, 5: .16, 6: .25})
        odds = {row['combination']: 200 for row in base['trifecta']}
        card = scent_box.select(base, base, odds)
        self.assertEqual(card['box_lanes'], [1, 4, 5])
        self.assertEqual(set(card['box_picks']), {
            '-'.join(map(str, p)) for p in permutations((1, 4, 5))})
        self.assertIn(len(card['cover_picks']), (2, 4))
        self.assertEqual(len(card['longshot_picks']), 3)
        self.assertEqual(len(card['picks']), len(set(card['picks'])))
        self.assertEqual(card['point_count'], len(card['picks']))
        self.assertEqual(card['stake_yen'], card['point_count'] * 100)
        self.assertIn('展示ST上位', card['boat_reasons']['4'])
        self.assertIn('まくり差し', card['boat_reasons']['4'])
        if card['cover_formation']:
            head, seconds, thirds = card['cover_formation'].split('-')
            self.assertEqual({f'{head}-{b}-{c}' for b in seconds for c in thirds},
                             set(card['cover_picks']))

    def test_unknown_odds_are_not_claimed_to_be_longshots(self):
        base = analysis()
        card = scent_box.select(base, base, {})
        self.assertEqual(card['longshot_picks'], [])
        self.assertFalse(card['odds_complete'])
        self.assertIsNone(card['estimated_return_yen'])

    def test_exhibition_is_required(self):
        base = analysis()
        base['preview']['exhibition_count'] = 5
        with self.assertRaises(ValueError):
            scent_box.select(base, base, {})


if __name__ == '__main__':
    unittest.main()
