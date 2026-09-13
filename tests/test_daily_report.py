from datetime import datetime
from itertools import permutations
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_report as r
import direct_discord_notify as base
import morning_all_races_discord as morning
import detailed_discord_notify as detailed

FIXTURES = Path(__file__).parent / 'fixtures'


def prediction(**changes):
    row = {'day': '20260913', 'jcd': '08', 'rno': 1, 'venue': '常滑',
           'deadline': '10:43', 'sent_at': '2026-09-13T10:30:00+09:00', 'phase': 'morning',
           'main': ['1-2-3'], 'cover': ['1-2-4'], 'outsiders': ['6-1-2'],
           'virtual_bets': [{'combination': '1-2-3', 'units': 1, 'odds': 999},
                            {'combination': '1-2-4', 'units': 2, 'odds': 999},
                            {'combination': '6-1-2', 'units': 3, 'odds': 999}],
           'virtual_total_units': 6}
    return {**row, **changes}


class SettlementTests(unittest.TestCase):
    def test_official_yen_payout_and_f_refund_weighted_by_units(self):
        official = r.parse_payout((FIXTURES / 'raceresult-20260912-08-10.html').read_text())
        self.assertEqual(official['payouts'], {'1-2-4': 670})
        self.assertEqual(official['refund_lanes'], [6])
        actual = r.settle(prediction(), official)
        self.assertEqual((actual['stake_yen'], actual['return_yen'], actual['refund_yen']), (600, 1640, 300))
        self.assertTrue(actual['virtual_hit'])
        total = r.totals([actual])
        self.assertEqual(total['profit_yen'], 1040)
        self.assertAlmostEqual(total['roi'], 1640 / 600 * 100)

    def test_dead_heat_multiple_official_payouts(self):
        official = r.parse_payout('<table><tbody><tr><td rowspan="2">3連単</td><td>1-2-3</td><td>&yen;1,200</td></tr><tr><td>1-3-2</td><td>&yen;900</td></tr></tbody></table>')
        self.assertEqual(official['payouts'], {'1-2-3': 1200, '1-3-2': 900})

    def test_unknown_payout_not_a_loss(self):
        pending = r.settle(prediction(), r.parse_payout('<p>結果待ち</p>'))
        stats = r.totals([pending])
        self.assertEqual(stats['total_stake_yen'], 600)
        self.assertEqual(stats['settled_stake_yen'], 0)
        self.assertIsNone(stats['roi'])
        self.assertIsNone(stats['hit_rate'])

    def test_all_void_refunds_and_zero_hit_denominator(self):
        settled = r.settle(prediction(), r.parse_payout('<tbody><tr><td>3連単</td><td>不成立</td></tr></tbody>'))
        self.assertEqual(settled['return_yen'], 600)
        stats = r.totals([settled])
        self.assertEqual(stats['roi'], 100)
        self.assertIsNone(stats['hit_rate'])
        self.assertEqual(stats['prediction_samples'], 0)

    def test_special_payout_is_not_prediction_hit(self):
        official = r.parse_payout('<tbody><tr><td>3連単</td><td>特払い &yen;70</td></tr></tbody>')
        settled = r.settle(prediction(), official)
        self.assertEqual(settled['return_yen'], 420)
        self.assertFalse(settled['hit_eligible'])

    def test_latest_delivery_once_and_never_after_close(self):
        old = prediction()
        latest = prediction(phase='final', sent_at='2026-09-13T10:35:00+09:00')
        late = prediction(sent_at='2026-09-13T10:43:00+09:00')
        unknown = prediction(sent_at='2026-09-13T10:31:00')
        chosen, excluded = r.latest_predictions([latest, old, late, unknown, latest], '20260913')
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen['08:1']['phase'], 'final')
        self.assertEqual(len(excluded), 2)

    def test_old_messages_have_no_invented_stakes_and_outsiders_count(self):
        row = prediction()
        del row['virtual_bets']
        del row['virtual_total_units']
        settled = r.settle(row, {'status': 'settled', 'payouts': {'6-1-2': 5000}, 'refund_lanes': []})
        self.assertTrue(settled['prediction_hit'])
        self.assertFalse(settled['plan_recorded'])
        self.assertEqual(settled['stake_yen'], 0)

    def test_invalid_allocation_and_undisclosed_bets_are_excluded(self):
        self.assertIsNone(r.virtual_plan(prediction(virtual_total_units=7)))
        self.assertIsNone(r.virtual_plan(prediction(virtual_bets=[{'combination': '5-4-3', 'units': 6}])))

    def test_report_missing_and_pending_are_explicit(self):
        report = r.build_report('20260913', [prediction()], {}, {'complete': True, 'races': {'08:1': {}, '08:2': {}}})
        self.assertEqual(report['missing_predictions'], ['08:2'])
        message = '\n'.join(r.report_messages(report))
        self.assertIn('暫定', message)
        self.assertIn('結果待ち 1R', message)
        self.assertIn('回収率 —', message)

    def test_report_retry_resumes_after_acknowledged_chunk(self):
        report = r.build_report('20260913', [prediction()], {}, {'complete': True, 'races': {'08:1': {}}})
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'SENT_PATH', Path(tmp) / 'sent.jsonl'), patch.object(r.time, 'sleep'):
            with patch.object(base, 'send_discord', side_effect=[None, RuntimeError('temporary')]) as send:
                with self.assertRaises(RuntimeError):
                    r.send_report(report)
                self.assertEqual(send.call_count, 2)
            with patch.object(base, 'send_discord') as send:
                self.assertEqual(r.send_report(report), 1)
                self.assertEqual(r.send_report(report), 0)
                self.assertEqual(send.call_count, 1)


class DeliveryAccountingTests(unittest.TestCase):
    def test_all_card_run_logs_only_sent_races_and_does_not_repeat(self):
        now = datetime(2026, 9, 13, 8, 45, tzinfo=base.JST)
        rows = [{'combination': '-'.join(map(str, combo)), 'probability': 1 / 120, 'odds': None, 'expected_value': None}
                for combo in permutations(range(1, 7), 3)]
        analysis = {'heads': {lane: 1 / 6 for lane in range(1, 7)}, 'trifecta': rows,
                    'preview': {'exhibition_count': 0}, 'model_version': 'test'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(base, 'LOG_PATH', Path(tmp) / 'predictions.jsonl'), patch.object(morning, 'CARD_DIR', Path(tmp) / 'cards'), patch.object(morning, 'datetime') as clock, patch.object(base, 'fetch'), patch.object(base, 'discover_venues', return_value=['08']), patch.object(base, 'deadlines', return_value=['10:00'] * 12), patch.object(base, 'analyze_official', return_value=analysis), patch.object(base, 'send_discord') as send, patch.object(morning.time, 'sleep'):
            clock.now.return_value = now
            self.assertEqual(morning.run_once(now), 12)
            saved = r.read_jsonl(base.LOG_PATH)
            self.assertEqual({row['rno'] for row in saved}, set(range(1, 13)))
            self.assertTrue(all(r.delivery_time(row) is not None for row in saved))
            calls = send.call_count
            self.assertEqual(morning.run_once(now), 0)
            self.assertEqual(send.call_count, calls)

    def test_today_all_tracks_and_no_second_initial_prediction(self):
        now = datetime(2026, 9, 13, 9, tzinfo=base.JST)
        policy = base.load_policy()
        self.assertTrue(base.required_venue(policy, '20260913', '07'))
        self.assertIsNone(base.due_phase(policy, now, '07', '15:00', {('20260913', '07', 1, 'morning')}, 1))
        self.assertFalse(base.required_venue(policy, '20260914', '07'))

    def test_chunk_ack_is_logged_even_if_next_chunk_fails(self):
        now = datetime(2026, 9, 13, 10, 30, tzinfo=base.JST)
        with patch.object(morning, 'datetime') as clock, patch.object(base, 'send_discord', side_effect=[None, RuntimeError('temporary')]), patch.object(base, 'log_prediction') as log, patch.object(morning.time, 'sleep'):
            clock.now.return_value = now
            with self.assertRaises(RuntimeError):
                morning.send_chunks('header', ['あ' * 1000, 'い' * 1000], [prediction(), prediction(rno=2)])
            self.assertEqual(log.call_count, 1)
            self.assertEqual(log.call_args.args[0]['rno'], 1)

    def test_race_that_closed_during_analysis_is_never_sent(self):
        now = datetime(2026, 9, 13, 10, 42, tzinfo=base.JST)
        with patch.object(morning, 'datetime') as clock, patch.object(base, 'send_discord') as send:
            clock.now.return_value = now
            self.assertEqual(morning.send_chunks('header', ['race'], [prediction()]), 0)
            send.assert_not_called()

    def test_long_message_keeps_every_virtual_stake(self):
        allocation = {'status': 'bet', 'total_units': 3, 'min_return_units': 6,
                      'bets': [{'combination': '1-2-3', 'odds': 8., 'units': 1}, {'combination': '1-2-4', 'odds': 3., 'units': 2}]}
        long_message = 'title\nformation\n**判断材料（6艇）**\n' + '選手データ' * 400 + '\n風速 1m'
        with patch.object(detailed, '_ORIGINAL_ANALYSIS_MESSAGE', return_value=long_message), patch.object(detailed, 'allocate_virtual_bets', return_value=allocation):
            msg = detailed.analysis_message_with_virtual('20260913', '08', 1, '10:43', 'final', {}, [], True)
        self.assertLessEqual(len(msg.encode('utf-16-le')) // 2, 2000)
        self.assertIn('1-2-3@8.0×1口', msg)
        self.assertIn('1-2-4@3.0×2口', msg)
        self.assertIn('2点・計3口（300円）', msg)


if __name__ == '__main__':
    unittest.main()
