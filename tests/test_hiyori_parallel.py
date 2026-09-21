from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hiyori_model as model
import hiyori_parallel as parallel
from prediction_engine import analyze_race


def fixtures():
    boats = [{'lane': n, 'predicted_course': n, 'racer_id': str(4000+n),
              'name': f'選手{n}', 'win_rate': 6, 'avg_st': .16, 'motor_number': n,
              'motor_top2_rate': 35, 'motor_top3_rate': 50} for n in range(1, 7)]
    official = analyze_race({'race': {'venue': '多摩川'}, 'boats': boats})
    official.update(inputs=boats, preview={'exhibition_count': 6, 'wind_speed': 2})
    source = {'source_url': 'https://kyoteibiyori.com/', 'rows': [], 'motor_last10': [], 'preview': []}
    for boat in boats:
        row = {'player_no': int(boat['racer_id']), 'course': boat['lane']}
        for c in range(1, 7):
            row.update({f'course{c}_shinnyu': 30, f'course{c}_1_ave': .7 if c == 1 else .1,
                        f'course{c}_2_ave': .8 if c == 1 else .3,
                        f'course{c}_3_ave': .9 if c == 1 else .5, f'start{c}_ave': .15})
        source['rows'].append(row)
    request = {'day': '20260921', 'jcd': '05', 'rno': 1, 'deadline': '10:30',
               'captured_at': '2026-09-21T10:15:00+09:00', 'official': official,
               'baseline_rows': official['trifecta'][:8]}
    return official, source, request


class HiyoriModelTests(unittest.TestCase):
    def test_baseline_is_unchanged_and_actual_entry_course_is_used(self):
        official, source, _ = fixtures()
        official['inputs'][0]['predicted_course'] = 2
        before = deepcopy(official)
        result = model.analyze(official, source, '20260921', '05', 1)
        self.assertEqual(official, before)
        self.assertEqual(result['features'][0]['course'], 2)
        self.assertEqual(result['features'][0]['course_win_rate'], .1)
        self.assertEqual(len(result['trifecta']), 120)
        self.assertAlmostEqual(sum(r['probability'] for r in result['trifecta']), 1)

    def test_wrong_racers_are_rejected(self):
        official, source, _ = fixtures()
        source['rows'][0]['player_no'] = 9999
        with self.assertRaises(ValueError):
            model.analyze(official, source, '20260921', '05', 1)

    def test_missing_measurements_stay_unknown_and_future_motor_results_are_excluded(self):
        official, source, _ = fixtures()
        source['motor_last10'] = [{'motor': 1, 'place_no': 5,
            'rank_01': 1, 'hiduke_01': 20260922, 'race_no_01': 1,
            'rank_02': 1, 'hiduke_02': 20260921, 'race_no_02': 1,
            'rank_03': 2, 'hiduke_03': 20260920, 'race_no_03': 10}]
        result = model.analyze(official, source, '20260921', '05', 1)
        self.assertEqual(result['features'][0]['motor_last10_ranks'], [2])
        self.assertNotIn('turn_grade', result['inputs'][0])
        self.assertNotIn('motor_last10', result['features'][0]['used'])


class HiyoriDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(parallel, 'ROOT', Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_deadline_is_rechecked_after_fetch_before_any_post(self):
        _, source, request = fixtures()
        with patch.object(parallel, 'before_deadline', side_effect=[True, False]), patch.object(parallel.hiyori_source, 'fetch_race', return_value=source), patch.object(parallel.discord, 'request_json') as sender:
            parallel.process(request)
        sender.assert_not_called()
        self.assertEqual(parallel.read(parallel.ROOT/'status/20260921_05_01.json')['state'], 'missed_deadline')
        self.assertFalse((parallel.ROOT/'deliveries/20260921_05_01.json').exists())

    def test_dedicated_destination_and_acknowledgement_prevent_repeated_posts(self):
        _, source, request = fixtures()
        env = {'HIYORI_DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/123/hiyori-token',
               'DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/999/main-token'}
        with patch.dict(parallel.os.environ, env), patch.object(parallel, 'before_deadline', return_value=True), patch.object(parallel.hiyori_source, 'fetch_race', return_value=source), patch.object(parallel.discord, 'request_json', return_value={'id': '777', 'channel_id': '888'}) as sender:
            parallel.process(request)
            parallel.process(request)
        sender.assert_called_once()
        self.assertIn('/123/hiyori-token', sender.call_args.args[0])
        self.assertNotIn('main-token', sender.call_args.args[0])
        self.assertEqual(sender.call_args.args[1]['flags'], 4096)
        receipt = parallel.read(parallel.ROOT/'deliveries/20260921_05_01.json')
        self.assertEqual(receipt['message_id'], '777')
        self.assertGreater(receipt['point_count'], 0)

    def test_source_failure_never_sends_a_baseline_copy_as_hiyori(self):
        _, _, request = fixtures()
        with patch.object(parallel, 'before_deadline', return_value=True), patch.object(parallel.hiyori_source, 'fetch_race', side_effect=ValueError), patch.object(parallel.discord, 'request_json') as sender:
            parallel.process(request)
        sender.assert_not_called()
        self.assertEqual(parallel.read(parallel.ROOT/'status/20260921_05_01.json')['state'], 'data_error')

    def test_late_capture_is_not_queued(self):
        official, _, request = fixtures()
        with patch.object(parallel, 'before_deadline', return_value=False):
            parallel.capture('20260921', '05', 1, '10:30', official, request['baseline_rows'])
        self.assertFalse((parallel.ROOT/'requests/20260921_05_01.json').exists())


if __name__ == '__main__':
    unittest.main()
