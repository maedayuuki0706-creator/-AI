import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_report
import detailed_discord_notify as app
import direct_discord_notify as base
import exhibition_final_discord as legacy
import race_notices as notices
import notification_runner


def withdrawal_html(lane=6):
    return f'<table><tbody><tr><td class="is-boatColor{lane}">{lane}</td><td colspan="7">欠場</td></tr></tbody></table>'


class RaceNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target,attr,value in [(base.delivery,'OUTBOX_ROOT',root/'outbox'),(base.audit,'AUDIT_ROOT',root/'audit'),(base,'CARD_DIR',root/'cards')]:
            item=patch.object(target,attr,value)
            item.start();self.addCleanup(item.stop)
        self.now = datetime(2026, 9, 13, 19, 20, tzinfo=base.JST)
        self.notice_patch = patch.object(notices, 'NOTICE_PATH', root / 'status.jsonl')
        self.notice_patch.start()
        self.addCleanup(self.notice_patch.stop)
        self.forecast_patch = patch.object(base, 'LOG_PATH', root / 'prediction.jsonl')
        self.forecast_patch.start()
        self.addCleanup(self.forecast_patch.stop)

    def test_exact_two_line_heading_for_withdrawal(self):
        self.assertEqual(notices.notice_message('若松', 10, 'withdrawn', ''), '若松 10レース\n欠場')

    def test_current_withdrawal_is_distinct_from_history_or_absent_data(self):
        self.assertEqual(notices.withdrawal_lanes(withdrawal_html()), [6])
        history = '<table><tbody><tr><td class="is-boatColor1">1</td>' + '<td>0.00</td>' * 7 + '<td>欠場</td></tr></tbody></table>'
        self.assertEqual(notices.withdrawal_lanes(history), [])
        self.assertEqual(notices.withdrawal_lanes('<p>データ待ち</p>'), [])
        with patch.object(base, 'fetch', return_value=''):
            kind, reason = base.unavailable_race_status('20260913', '20', 10)
        self.assertEqual(kind, 'unavailable')
        self.assertIn('欠場は未確認', reason)

    def test_confirmed_withdrawal_never_enters_the_prediction_engine(self):
        with patch.object(base, 'fetch', return_value=withdrawal_html()), patch.object(base, 'parse_racelist_boats') as parse:
            self.assertIsNone(base.analyze_official('20260913', '20', 10))
            parse.assert_not_called()

    def test_acknowledged_notice_is_not_resent_or_counted_as_forecast(self):
        with patch.object(base, 'datetime') as clock, patch.object(base, 'send_discord',return_value={'id':'123','channel_id':'456'}) as send:
            clock.now.return_value = self.now
            for _ in range(2):
                base.send_race_notice('20260913', '20', 10, '19:40', 'withdrawn', '6号艇が欠場。')
            self.assertEqual(send.call_count, 1)
            self.assertTrue(send.call_args.args[0].startswith('若松 10レース\n欠場\n'))
        self.assertEqual(len(notices.read_notices()), 1)
        self.assertFalse(base.LOG_PATH.exists())

    def test_failed_post_can_retry_without_fabricating_a_delivery(self):
        with patch.object(base, 'datetime') as clock, patch.object(base, 'send_discord', side_effect=RuntimeError('temporary')):
            clock.now.return_value = self.now
            with self.assertRaises(RuntimeError):
                base.send_race_notice('20260913', '20', 10, '19:40', 'waiting', '展示待ち')
        self.assertEqual(notices.read_notices(), [])

    def test_closed_race_is_not_posted_and_dry_run_is_read_only(self):
        with patch.object(base, 'datetime') as clock, patch.object(base, 'send_discord',return_value={'id':'123','channel_id':'456'}) as send:
            clock.now.return_value = self.now
            self.assertFalse(base.send_race_notice('20260913', '20', 10, '19:21', 'withdrawn', ''))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(base.send_race_notice('20260913', '20', 10, '19:40', 'withdrawn', '', now=self.now, dry_run=True))
            send.assert_not_called()
        self.assertEqual(notices.read_notices(), [])

    def test_waiting_notice_does_not_consume_the_final_prediction_slot(self):
        analysis = {'inputs': [{'lane': lane} for lane in range(1, 7)], 'preview': {'exhibition_count': 0}}
        existing = {('20260913', '20', 1, 'morning')}
        policy = base.load_policy()
        with patch.object(base, 'datetime') as clock, patch.object(base, 'fetch'), patch.object(base, 'discover_venues', return_value=['20']), patch.object(base, 'deadlines', return_value=['19:40']), patch.object(base, 'load_deliveries', return_value=existing), patch.object(base, 'analyze_official', return_value=analysis), patch.object(base, 'make_analysis_message', return_value='final forecast'), patch.object(base, 'displayed_picks', return_value=[{'combination': '1-2-3'}]), patch.object(base, 'send_discord',return_value={'id':'123','channel_id':'456'}) as send, contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value = self.now
            self.assertEqual(base.run_once(self.now), 0)
            self.assertIn('見送り推奨（データ待ち）', send.call_args.args[0])
            self.assertFalse(base.LOG_PATH.exists())
            self.assertEqual(base.due_phase(policy, self.now, '20', '19:40', existing, 1), 'final')
            analysis.update(preview={'exhibition_count': 6}, model_version='test', grade='B', heads={}, previous_form={})
            self.assertEqual(base.run_once(self.now), 0)
            self.assertEqual(send.call_count, 2)
            self.assertEqual(json.loads(base.LOG_PATH.read_text())['phase'], 'final')

    def test_runner_posts_withdrawal_without_betting_and_continues(self):
        with patch.object(base, 'datetime') as clock, patch.object(base, 'fetch', return_value=withdrawal_html()), patch.object(base, 'discover_venues', return_value=['20']), patch.object(base, 'deadlines', return_value=['19:40']), patch.object(base, 'analyze_official', return_value=None), patch.object(base, 'send_discord',return_value={'id':'123','channel_id':'456'}) as send, contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value = self.now
            self.assertEqual(base.run_once(self.now), 0)
            self.assertIn('若松 1レース\n欠場', send.call_args.args[0])
        self.assertFalse(base.LOG_PATH.exists())

    def test_ai_filtered_race_still_receives_pass_reason(self):
        policy = {**base.load_policy(), 'all_races': {}}
        analysis = {'inputs': [{'lane': lane} for lane in range(1, 7)],
                    'preview': {'exhibition_count': 6, 'wind_speed': 0, 'wave_cm': 0}, 'grade': 'C', 'trifecta': []}
        with patch.object(base, 'datetime') as clock, patch.object(base, 'fetch'), patch.object(base, 'load_policy', return_value=policy), patch.object(base, 'discover_venues', return_value=['20']), patch.object(base, 'deadlines', return_value=['19:40']), patch.object(base, 'analyze_official', return_value=analysis), patch.object(base, 'send_discord',return_value={'id':'123','channel_id':'456'}) as send, contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value = self.now
            self.assertEqual(base.run_once(self.now), 0)
            self.assertIn('若松 1レース\n見送り推奨', send.call_args.args[0])
            self.assertIn('AI評価C', send.call_args.args[0])

    def test_allocation_pass_has_prominent_recommendation_and_zero_units(self):
        allocation = {'status': 'pass', 'reason': '期待値条件未達', 'bets': [], 'total_units': 0}
        with patch.object(app, '_ORIGINAL_ANALYSIS_MESSAGE', return_value='参考買い目'), patch.object(app, 'allocate_virtual_bets', return_value=allocation):
            message = app.analysis_message_with_virtual('20260913', '20', 10, '19:40', 'final', {}, [], True)
        self.assertTrue(message.startswith('若松 10レース\n見送り推奨\n理由：期待値条件未達'))
        self.assertIn('0口', message)

    def test_legacy_entry_preserves_data_wait_reason_instead_of_fake_missing_boats(self):
        analysis = {'inputs': [{'lane': lane} for lane in range(1, 7)], 'preview': {'exhibition_count': 0}, 'trifecta': []}
        with patch.object(legacy, '_original_analyze', return_value=analysis):
            actual = legacy.analyze_after_exhibition('20260913', '20', 10)
        self.assertEqual(len(actual['inputs']), 6)
        self.assertTrue(actual['delivery_wait_reasons'])

    def test_confirmed_withdrawal_excludes_previous_morning_forecast_from_stats(self):
        notices.record_notice({'day': '20260913', 'jcd': '20', 'rno': 10, 'deadline': '19:40', 'status': 'withdrawn', 'sent_at': self.now.isoformat()})
        row = {'day': '20260913', 'jcd': '20', 'rno': 10, 'deadline': '19:40', 'phase': 'morning', 'sent_at': '2026-09-13T08:30:00+09:00', 'main': ['1-2-3']}
        chosen, excluded = daily_report.latest_predictions([row], '20260913')
        self.assertEqual(chosen, {})
        self.assertEqual(len(excluded), 1)

    def test_scheduled_runner_rechecks_and_recovers_within_budget(self):
        elapsed, codes = [0], [1, 0]
        def attempt():
            elapsed[0] += 10
            return codes.pop(0)
        def pause(seconds):
            elapsed[0] += seconds
        self.assertEqual(notification_runner.run(210, attempt=attempt, clock=lambda: elapsed[0], pause=pause, is_open=lambda: True), 1)
        self.assertEqual(codes, [])
        self.assertEqual(elapsed[0], 50)

    def test_manual_run_once_and_outside_race_hours_no_post(self):
        with patch.object(notification_runner.app, 'main') as attempt:
            attempt.return_value = 0
            self.assertEqual(notification_runner.run(0, attempt=attempt, is_open=lambda: True), 0)
            self.assertEqual(attempt.call_count, 1)
            notification_runner.run(600, attempt=attempt, is_open=lambda: False)
            self.assertEqual(attempt.call_count, 1)


if __name__ == '__main__':
    unittest.main()
