import contextlib
from datetime import datetime
import io
from itertools import permutations
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from discord_formation import compress_picks, expand_formation, formation_summary
from discord_detail_formatter import format_detailed_message
import direct_discord_notify as notifier
from prediction_engine import analyze_race


class FormationTests(unittest.TestCase):
    def test_compact_known_formation_has_four_points(self):
        picks = ['1-2-3', '1-2-4', '1-3-2', '1-3-4']
        self.assertEqual(compress_picks(picks), [{'text': '1-23-234', 'point_count': 4}])

    def test_overlapping_lanes_are_excluded(self):
        picks = expand_formation('13-1356-1356')
        self.assertEqual(len(picks), 12)
        self.assertNotIn('1-1-3', picks)
        self.assertEqual(compress_picks(sorted(picks)), [{'text': '13-1356-1356', 'point_count': 12}])

    def test_compression_never_adds_tickets_or_double_counts(self):
        rng = random.Random(13)
        universe = ['-'.join(map(str, order)) for order in permutations(range(1, 7), 3)]
        for size in (1, 3, 6, 8):
            for _ in range(12):
                picks = rng.sample(universe, size)
                groups = compress_picks(picks)
                expanded = [pick for group in groups for pick in expand_formation(group['text'])]
                self.assertEqual(set(expanded), set(picks))
                self.assertEqual(len(expanded), size)
                self.assertEqual(sum(g['point_count'] for g in groups), size)

    def test_duplicates_across_main_and_cover_count_only_once(self):
        summary = formation_summary(['1-2-3', '1-2-3'], ['1-2-3', '2-1-3'])
        self.assertEqual(summary['point_count'], 2)
        self.assertEqual([s['point_count'] for s in summary['sections']], [1, 1])
        self.assertEqual(formation_summary([])['point_count'], 0)

    def test_invalid_tickets_are_rejected(self):
        for picks in (['1-1-2'], ['1-2-7'], ['1-2'], ['not-a-ticket']):
            with self.assertRaises(ValueError):
                compress_picks(picks)

    def test_legacy_formatter_includes_count_and_handles_missing_local_data(self):
        body = format_detailed_message('常滑', 1, '11:00', ['1-2-3', '1-2-4'], False, '独自AI', None,
            {'trifecta': [], 'boats': []}, [{'lane': 1, 'local_win_rate': None}])
        self.assertIn('3連単フォーメーション', body)
        self.assertIn('`1-2-34`（2点）', body)
        self.assertIn('合計 2点', body)

    def test_actual_delivery_runner_renders_and_logs_the_same_six_points(self):
        boats = [{'lane': lane, 'predicted_course': lane, 'name': '選手', 'win_rate': 6.0,
                  'motor_top2_rate': 40.0, 'avg_st': .15} for lane in range(1, 7)]
        analysis = analyze_race({'race': {'venue': '常滑'}, 'boats': boats})
        analysis.update(inputs=boats, grade=None, previous_form={},
            heads={lane: sum(p['probability'] for p in analysis['trifecta'] if p['combination'].startswith(f'{lane}-')) for lane in range(1, 7)},
            preview={'exhibition_count': 0, 'wind_speed': None, 'wave_cm': None, 'entry_observed': False})
        now = datetime(2026, 9, 13, 8, 30, tzinfo=notifier.JST)
        with tempfile.TemporaryDirectory() as tmp, patch.object(notifier, 'LOG_PATH', Path(tmp) / 'log.jsonl'), \
             patch.object(notifier, 'datetime') as clock, patch.object(notifier, 'fetch'), \
             patch.object(notifier, 'discover_venues', return_value=['08']), \
             patch.object(notifier, 'deadlines', return_value=['11:00']), \
             patch.object(notifier, 'analyze_official', return_value=analysis), \
             patch.object(notifier, 'send_discord') as send, contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value = now
            self.assertEqual(notifier.run_once(now), 0)
            self.assertEqual(send.call_count, 1)
            body = send.call_args.args[0]
            row = json.loads(notifier.LOG_PATH.read_text())
            self.assertIn('3連単フォーメーション', body)
            self.assertIn('合計 6点', body)
            self.assertLess(len(body.encode('utf-16-le')) // 2, 2000)
            self.assertEqual(row['message_format'], 'formation-v1')
            self.assertEqual(row['point_count'], len(set(row['all_picks'])))
            expanded = set()
            for section in row['formation_sections']:
                for group in section['formations']:
                    self.assertIn(f"`{group['text']}`（{group['point_count']}点）", body)
                    expanded.update(expand_formation(group['text']))
            self.assertEqual(expanded, set(row['all_picks']))
            self.assertEqual(notifier.run_once(now), 0)
            self.assertEqual(send.call_count, 1)


if __name__ == '__main__':
    unittest.main()
