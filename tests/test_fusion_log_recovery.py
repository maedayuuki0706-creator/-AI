"""Recovery boundaries and a real local Git remote; no live race forecasts."""
from copy import deepcopy
from datetime import timedelta
import gzip
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import fusion_shadow as core
import fusion_shadow_runner as runner
from research.fusion_log_recovery import pilot
from research.venue_specialists_v1 import worker
from research.venue_specialists_v1.tests import test_phase1 as phase1_tests
from test_fusion_shadow import NOW, record, result


class CaptureRecoveryTests(unittest.TestCase):
    def test_cutoff_prevents_even_starting_source_acquisition(self):
        for now in (NOW + timedelta(minutes=12), NOW + timedelta(minutes=16)):
            with self.subTest(now=now), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(runner, 'now_jst', return_value=now), \
                    patch.object(runner, 'build_live', side_effect=AssertionError('No late acquisition')):
                with self.assertRaises(ValueError):
                    runner.capture_one(tmp, '20261012', '06', 1, '10:15')
                self.assertEqual(list(Path(tmp).rglob('*.json')), [])

    def test_interrupted_pair_resumes_exact_original_without_recalculation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'now_jst', return_value=NOW):
            original = record()
            write_once = core.write_once
            def interrupted(path, value):
                if '/predictions/' in str(path):
                    raise RuntimeError('Simulated termination after snapshot')
                return write_once(path, value)
            with patch.object(runner, 'build_live', return_value=(deepcopy(original), {'fixture': 'pre-race'})), \
                    patch.object(core, 'write_once', side_effect=interrupted):
                with self.assertRaises(RuntimeError):
                    runner.capture_one(tmp, '20261012', '06', 1, '10:15')
            snapshot = Path(tmp) / 'snapshots/20261012/20261012_06_01.json.gz'
            before = snapshot.read_bytes()
            with patch.object(runner, 'build_live', side_effect=AssertionError('No recalculation')):
                saved = runner.capture_one(tmp, '20261012', '06', 1, '10:15')
            self.assertEqual(snapshot.read_bytes(), before)
            frozen = runner.load(Path(tmp) / 'predictions/20261012/20261012_06_01.json')
            self.assertEqual(frozen['created_at'], original['created_at'])
            self.assertEqual(frozen['models'], original['models'])
            self.assertEqual(frozen['provenance']['snapshot_sha256'], core.sha256(before).hexdigest())
            self.assertEqual(saved['status'], 'frozen')
            self.assertEqual(runner.capture_one(tmp, '20261012', '06', 1, '10:15')['status'], 'already_frozen')

    def test_expired_orphan_is_retained_without_late_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'snapshots/20261012/20261012_06_01.json.gz'
            content = gzip.compress(json.dumps({'prediction_original': record()}).encode())
            core.write_once(path, content)
            with patch.object(runner, 'now_jst', return_value=NOW + timedelta(minutes=16)), \
                    patch.object(runner, 'build_live', side_effect=AssertionError('No backfill')):
                with self.assertRaises(ValueError):
                    runner.capture_one(tmp, '20261012', '06', 1, '10:15')
            self.assertEqual(path.read_bytes(), content)
            self.assertFalse((Path(tmp) / 'predictions').exists())

    def test_corrupt_duplicate_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = record(); bad['models']['fusion']['picks'] = []
            core.write_once(Path(tmp) / 'predictions/20261012/20261012_06_01.json', bad)
            with self.assertRaises(ValueError):
                runner.capture_one(tmp, '20261012', '06', 1, '10:15')

    def test_incomplete_exhibition_never_saves_a_forecast(self):
        import direct_discord_notify as base
        import hiyori_source
        import hiyori_model
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'now_jst', return_value=NOW), \
                patch.object(base, 'analyze_official', return_value={'preview': {'exhibition_count': 5}}), \
                patch.object(hiyori_source, 'fetch_race', return_value={'rows': []}), \
                patch.object(hiyori_model, 'analyze', side_effect=AssertionError('Do not analyze missing input')):
            with self.assertRaises(ValueError):
                runner.capture_one(tmp, '20261012', '06', 1, '10:15')
            self.assertFalse((Path(tmp) / 'predictions').exists())

    def test_timeout_retains_last_safe_stage(self):
        race = {'key': '20261012_06_01', 'day': '20261012', 'jcd': '06', 'rno': 1, 'deadline': '10:15'}
        stderr = b'{"capture_stage":"official_started","at":"fixture"}\n'
        exc = subprocess.TimeoutExpired(['python'], 55, stderr=stderr)
        with patch.object(subprocess, 'run', side_effect=exc):
            out = runner._capture_child('.', race, 55)
        self.assertEqual(out['status'], 'budget_exceeded')
        self.assertEqual(out['stages'][-1]['capture_stage'], 'official_started')
        self.assertNotIn('prediction', out)

    def test_timeout_fails_health_and_does_not_request_results_before_push(self):
        schedule = {'venues': {'23': ['10:15', '10:20', '10:25', '10:28'], '06': ['10:15']}, 'errors': {}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'now_jst', return_value=NOW), \
                patch.object(runner, 'collect_card', return_value=schedule), \
                patch.object(runner, '_capture_child', return_value={'key': '20261012_23_01', 'status': 'budget_exceeded'}) as child, \
                patch.object(runner, 'collect_results', side_effect=AssertionError('No result before receipt')):
            self.assertEqual(runner.run(tmp, only_venues={'23'}, only_rnos={1, 2, 3},
                                        max_captures=1, skip_results=True), 1)
            self.assertEqual(child.call_count, 1)
            health = runner.load(Path(tmp) / 'heartbeat.json')
            self.assertEqual(health['status'], 'capture_incomplete')
            self.assertEqual(health['due_races'], 3)
            self.assertEqual(len(health['captures']), 3)

    def test_missing_schedule_is_failure_not_verified_zero(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'now_jst', return_value=NOW), \
                patch.object(runner, 'collect_card', return_value={'venues': {}, 'errors': {'23': 'unavailable'}}):
            self.assertEqual(runner.run(tmp, skip_results=True), 1)

    def test_saved_result_resumes_evaluation_without_refetch_or_original_change(self):
        import direct_discord_notify as base
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'now_jst', return_value=NOW + timedelta(minutes=25)):
            root = Path(tmp); prediction = record(); name = prediction['key'] + '.json'
            checkpoint = {'prediction_digest': prediction['digest'], 'commit_sha': 'a' * 40,
                          'prediction_committed_at': '2026-10-12T10:01:00+09:00'}
            settled = result(prediction, prediction_commit_sha='a' * 40,
                             source_url=base.official_url('raceresult', '20261012', '06', 1))
            for kind, value in [('predictions', prediction), ('checkpoints', checkpoint), ('results', settled)]:
                core.write_once(root / kind / '20261012' / name, value)
            original = (root / 'predictions/20261012' / name).read_bytes()
            with patch.object(base, 'fetch', side_effect=AssertionError('Reuse saved official result')):
                out = runner.collect_results(root, time.monotonic() + 30, max_fetch=2)
            self.assertEqual(out, {'settled': 1, 'errors': []})
            self.assertEqual((root / 'predictions/20261012' / name).read_bytes(), original)
            self.assertTrue((root / 'evaluations/20261012' / name).is_file())


class PilotPersistenceTests(unittest.TestCase):
    def test_original_remote_receipt_and_result_have_strict_order(self):
        events = []
        with patch.object(runner, 'now_jst', return_value=NOW), \
                patch.object(runner, 'run', side_effect=lambda *a, **k: events.append('capture') or 0), \
                patch.object(pilot, 'persist', side_effect=lambda *a, **k: events.append('push') or 'a' * 40), \
                patch.object(runner, 'checkpoint', side_effect=lambda *a: events.append('receipt') or 1), \
                patch.object(runner, 'collect_results', side_effect=lambda *a, **k: events.append('result') or {'settled': 0, 'errors': []}), \
                patch.object(runner, 'write_summary', return_value={}):
            pilot.tick('.', '20261012')
        self.assertEqual(events, ['capture', 'push', 'receipt', 'push', 'result', 'push'])

    def test_failed_remote_save_prevents_receipt_and_result(self):
        with patch.object(runner, 'now_jst', return_value=NOW), patch.object(runner, 'run', return_value=1), \
                patch.object(pilot, 'persist', side_effect=RuntimeError('Push failed')), \
                patch.object(runner, 'checkpoint', side_effect=AssertionError('No receipt')), \
                patch.object(runner, 'collect_results', side_effect=AssertionError('No result')):
            with self.assertRaises(RuntimeError): pilot.tick('.', '20261012')

    def test_wrong_day_and_overnight_never_make_source_requests(self):
        for day, now in [('20261011', NOW), ('20261012', NOW.replace(hour=2))]:
            with patch.object(runner, 'now_jst', return_value=now), \
                    patch.object(runner, 'run', side_effect=AssertionError('No source requests')):
                with self.assertRaises(ValueError): pilot.tick('.', day)

    def test_real_remote_retry_with_empty_index_and_exact_snapshot_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = phase1_tests.PersistenceResumeTests()._setup(tmp)
            worker.git(state, 'push', 'origin', 'HEAD:refs/heads/' + pilot.BRANCH)
            root = state / pilot.PREFIX
            with patch.object(runner, 'now_jst', return_value=NOW), \
                    patch.object(runner, 'build_live', return_value=(record(), {'fixture': 'pre-race'})):
                runner.capture_one(root, '20261012', '06', 1, '10:15')
            real_git = worker.git
            def fail_push(*args):
                if args[1] == 'push': raise subprocess.CalledProcessError(1, ['git', 'push'])
                return real_git(*args)
            with patch.object(worker, 'git', side_effect=fail_push):
                with self.assertRaises(RuntimeError):
                    worker.persist(state, 'fixture failed push', attempts=1, fusion_pilot_day='20261012')
            self.assertEqual(worker.git(state, 'diff', '--cached', '--name-only'), '')
            sha = worker.persist(state, 'fixture resume', pause=lambda _: None, fusion_pilot_day='20261012')
            with patch.object(runner, 'now_jst', return_value=NOW + timedelta(minutes=1)):
                snapshot = root / 'snapshots/20261012/20261012_06_01.json.gz'
                original = snapshot.read_bytes()
                snapshot.write_bytes(original + b'corrupt')
                with self.assertRaises(ValueError): runner.checkpoint(root, sha)
                snapshot.write_bytes(original)
                self.assertEqual(runner.checkpoint(root, sha), 1)
            rec = runner.load(root / 'checkpoints/20261012/20261012_06_01.json')
            self.assertTrue(rec['eligible_checkpoint'])
            self.assertTrue(rec['snapshot_verified_at_remote_commit'])
            self.assertEqual(rec['commit_sha'], sha)

    def test_fusion_persister_rejects_modifying_originals_and_production_paths(self):
        with self.assertRaises(ValueError):
            worker._validate_paths('M\tdata/fusion_shadow/predictions/20261012/x.json', prefix=pilot.PREFIX, mutable=set())
        with self.assertRaises(ValueError):
            worker._validate_paths('A\tdata/prediction_log.jsonl', prefix=pilot.PREFIX, mutable=set())


if __name__ == '__main__':
    unittest.main()
