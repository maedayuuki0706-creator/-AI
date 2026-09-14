import unittest

import daily_report as report
from daily_report_format import report_payloads
from discord_formation import expand_formation


def prediction():
    return {'day': '20260913', 'jcd': '08', 'rno': 5, 'deadline': '12:38',
            'sent_at': '2026-09-13T12:23:00+09:00', 'phase': 'final',
            'main': ['2-5-1', '2-5-3'], 'cover': ['5-2-1'], 'outsiders': ['1-5-2'],
            'virtual_bets': [{'combination': '5-2-1', 'units': 1}], 'virtual_total_units': 1}


class DailyFormatTests(unittest.TestCase):
    def build(self, result):
        return report.build_report('20260913', [prediction()], {'08:5': result},
                                   {'complete': True, 'races': {'08:5': {}, '08:6': {}}})

    def test_one_venue_message_keeps_picks_points_result_and_real_newlines(self):
        data = self.build({'status': 'settled', 'payouts': {'2-5-1': 930}, 'refund_lanes': []})
        payloads = report_payloads(data)
        self.assertEqual(len(payloads), 2)
        fields = payloads[1]['embeds'][0]['fields']
        self.assertEqual(len(fields), 12)
        field = fields[4]
        self.assertIn('予想4点', field['name'])
        self.assertIn('結果：2-5-1（930円）', field['value'])
        self.assertIn('本線的中', field['value'])
        self.assertNotIn('\\n', field['value'])
        lines = field['value'].splitlines()
        for label, picks in [('本線', prediction()['main']), ('抑え', prediction()['cover']), ('穴', prediction()['outsiders'])]:
            i = next(i for i, line in enumerate(lines) if line.startswith('**' + label))
            expanded = set().union(*(expand_formation(s) for s in lines[i + 1].split(' ／ ')))
            self.assertEqual(expanded, set(picks))
        self.assertIn('配信記録なし', fields[5]['value'])

    def test_uniform_comparison_does_not_change_recorded_virtual_plan(self):
        data = self.build({'status': 'settled', 'payouts': {'2-5-1': 930}, 'refund_lanes': []})
        self.assertEqual(data['uniform_totals']['total_stake_yen'], 400)
        self.assertEqual(data['uniform_totals']['return_yen'], 930)
        self.assertEqual(data['totals']['total_stake_yen'], 100)
        self.assertEqual(data['totals']['return_yen'], 0)
        self.assertEqual(data['section_totals']['main']['virtual_hits'], 1)
        self.assertEqual(data['section_totals']['cover']['virtual_hits'], 0)

    def test_full_refund_is_not_displayed_as_loss_or_hit(self):
        data = self.build({'status': 'settled', 'payouts': {'4-6-3': 2660}, 'refund_lanes': [5]})
        uniform = data['uniform_totals']
        self.assertEqual(uniform['return_yen'], 400)
        self.assertEqual(uniform['virtual_hit_samples'], 0)
        self.assertIsNone(uniform['hit_rate'])
        field = report_payloads(data)[1]['embeds'][0]['fields'][4]
        self.assertIn('全点が返還', field['value'])
        self.assertNotIn('不的中', field['value'])


if __name__ == '__main__':
    unittest.main()
