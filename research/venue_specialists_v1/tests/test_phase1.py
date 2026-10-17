import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research.scenario_v2 import engine as scenario
from research.scenario_v2.collector import save_immutable
from research.scenario_v2.tests.test_adapter_batch import source_fixture
from research.venue_specialists_v1 import engine, run, worker
from research.venue_specialists_v1.log_contract import (
    capture_yuuki, descriptor, verify_yuuki, validate_receipt, FrozenBaseline,
)
from research.venue_specialists_v1.phase1_metrics import comparison, save_report, build_report
from research.venue_specialists_v1.tests.test_engine import fixture, FakeOfficial, JST

NOW = datetime(2026, 10, 17, 11, 1, tzinfo=JST)


def baseline(snapshot):
    def load(key):
        value = copy.deepcopy(snapshot)
        value['baseline_picks'] = sorted(scenario.COMBINATIONS)[:10]
        value['baseline_ranking'] = sorted(scenario.COMBINATIONS)
        return value, {'remote_sha': 'a' * 40, 'baseline_digest': 'b' * 64,
                       'remote_observed_at': NOW.isoformat()}
    return load


def originals(tmp, *, day='20261017', code='16'):
    snapshot = fixture(code, day)
    now = datetime.strptime(day + ' 11:01', '%Y%m%d %H:%M').replace(tzinfo=JST)
    f = engine.analyze(snapshot, mode='live', now=now.isoformat())
    rec = {'race_id': f['race_id'], 'digest': f['digest'], 'checked_at': (now + timedelta(seconds=1)).isoformat(),
           'commit_sha': 'a' * 40, 'status': 'confirmed_before_deadline'}
    root = Path(tmp)
    name = f['race_id'] + '.json'
    for kind, value in [('inputs', snapshot), ('forecasts', f), ('receipts', rec)]:
        save_immutable(root / kind / day / name, value)
    # Include all seven race identities, but preserve six deliberately missing.
    inventory = {'day': day, 'schedules': {code: ['10:00', '10:10', '10:20', '10:30', '10:40', '10:50', '11:30']}, 'errors': []}
    save_immutable(root / 'schedules' / day / '110100.json', inventory)
    return snapshot, f, rec


def result_for(f, combination=None):
    return {'race_id': f['race_id'], 'status': 'settled', 'observed_at': '2026-10-17T12:00:00+09:00',
            'payouts': {combination or f['virtual_card'][0]['combination']: 2340},
            'refund_lanes': [], 'source_url': 'https://www.boatrace.jp/owpc/pc/race/raceresult'}


class YuukiCaptureTests(unittest.TestCase):
    def test_complete_six_scenarios_existing_ten_ticket_policy_and_remote_receipt(self):
        snapshot = fixture()
        with TemporaryDirectory() as tmp:
            out = capture_yuuki(snapshot, tmp, clock=lambda: NOW, baseline=baseline(snapshot))
            self.assertEqual(out['status'], 'locally_frozen_uncheckpointed')
            root = Path(tmp)
            key = '20261017_16_07'
            f = json.loads((root / 'yuuki/forecasts/20261017' / (key + '.json')).read_text())
            self.assertTrue(descriptor(f)['complete_card'])
            self.assertEqual(f['virtual_card']['policy'], 'retain-main6-flow4-v1')
            self.assertEqual(len(f['lanes']), 6)
            self.assertTrue(all(len(h['reactions']) == 5 for b in f['lanes'] for h in b['hypotheses']))
            show = lambda sha, path: (root / path.removeprefix(worker.PREFIX + '/')).read_text()
            rec = verify_yuuki(tmp, 'a' * 40, git_show=show, confirmed_at=NOW + timedelta(seconds=1))[0]
            self.assertEqual(rec['status'], 'confirmed_before_deadline')
            validate_receipt(f, rec)
            before = (root / 'yuuki/forecasts/20261017' / (key + '.json')).read_bytes()
            capture_yuuki(snapshot, tmp, clock=lambda: NOW + timedelta(seconds=3), baseline=baseline(snapshot))
            self.assertEqual(before, (root / 'yuuki/forecasts/20261017' / (key + '.json')).read_bytes())

    def test_no_baseline_is_partial_never_fake_ten_point_forecast(self):
        with TemporaryDirectory() as tmp:
            out = capture_yuuki(fixture(), tmp, clock=lambda: NOW)
            self.assertEqual(out['status'], 'partial_no_baseline_card')
            self.assertFalse(list((Path(tmp) / 'yuuki/forecasts').glob('*/*.json')))
            self.assertEqual(len(list((Path(tmp) / 'yuuki/partial_scenarios').glob('*/*.json'))), 1)
            # A genuinely new pre-deadline baseline may complete a separate full
            # forecast; the earlier partial original remains unchanged.
            out = capture_yuuki(fixture(), tmp, clock=lambda: NOW, baseline=baseline(fixture()))
            self.assertEqual(out['status'], 'locally_frozen_uncheckpointed')

    def test_partial_retry_does_not_generate_an_unsaved_duplicate_scenario(self):
        with TemporaryDirectory() as tmp:
            capture_yuuki(fixture(), tmp, clock=lambda: NOW)
            with patch.object(scenario, 'generate', side_effect=AssertionError('Reuse the already saved partial original')):
                out = capture_yuuki(fixture(), tmp, clock=lambda: NOW + timedelta(seconds=30))
            self.assertEqual(out['status'], 'partial_scenario_already_saved')

    def test_late_generation_never_backfills_even_with_old_input(self):
        with TemporaryDirectory() as tmp:
            out = capture_yuuki(fixture(), tmp, clock=lambda: NOW + timedelta(minutes=30), baseline=baseline(fixture()))
            self.assertEqual(out['status'], 'capture_cutoff_closed_no_backfill')
            self.assertFalse(list(Path(tmp).rglob('*.json')))

    def test_result_contamination_rejected(self):
        payload = fixture()
        payload['environment']['actual_st'] = .1
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            capture_yuuki(payload, tmp, clock=lambda: NOW)

    def test_wrong_baseline_entry_remains_partial(self):
        bad = fixture()
        bad['boats'][0]['racer_id'] = '9999'
        with TemporaryDirectory() as tmp:
            out = capture_yuuki(fixture(), tmp, clock=lambda: NOW, baseline=baseline(bad))
            self.assertEqual(out['status'], 'partial_no_baseline_card')
            self.assertIn('entrant', out['reason'])

    def test_remote_mismatch_and_late_remote_receipt_not_success(self):
        with TemporaryDirectory() as tmp:
            capture_yuuki(fixture(), tmp, clock=lambda: NOW, baseline=baseline(fixture()))
            with self.assertRaises(ValueError):
                verify_yuuki(tmp, 'a' * 40, git_show=lambda *args: '{}', confirmed_at=NOW)
            show = lambda sha, path: (Path(tmp) / path.removeprefix(worker.PREFIX + '/')).read_text()
            rec = verify_yuuki(tmp, 'a' * 40, git_show=show, confirmed_at=NOW + timedelta(hours=1))[0]
            self.assertEqual(rec['status'], 'late_remote_save_excluded')

    def test_partial_inputs_resume_without_refetching_specialist(self):
        with TemporaryDirectory() as tmp:
            source = FakeOfficial()
            clock = lambda: datetime(2026, 10, 17, 10, 0, tzinfo=JST)
            run.collect_race('20261017', '16', 1, '10:25', tmp, official=source, clock=clock)
            with patch.object(source, 'fetch', side_effect=AssertionError('No duplicate official request')):
                out = run.collect_race('20261017', '16', 1, '10:25', tmp, official=source, clock=clock)
            self.assertEqual(out['status'], 'already_frozen')

    def test_lazy_baseline_fetch_once_no_write_to_source_branch(self):
        record, cp = source_fixture()
        clock = lambda: datetime(2026, 10, 16, 18, 52, tzinfo=JST)
        loader = FrozenBaseline('.', clock)
        calls = []
        def fake(*args):
            calls.append(args)
            if args[0] == 'rev-parse': return 'a' * 40
            if args[0] == 'show': return json.dumps(cp if '/checkpoints/' in args[1] else record)
            return ''
        with patch.object(loader, '_git', side_effect=fake):
            loader(record['key']); loader(record['key'])
        self.assertEqual(sum(x[0] == 'fetch' for x in calls), 1)
        self.assertFalse(any(x[0] in ('push', 'checkout', 'commit') for x in calls))

    def test_empty_recovery_archive_falls_back_to_existing_frozen_original(self):
        record, cp = source_fixture()
        clock = lambda: datetime(2026, 10, 16, 18, 52, tzinfo=JST)
        loader = FrozenBaseline('.', clock)
        calls = []
        def fake(*args):
            calls.append(args)
            if args[0] == 'rev-parse':
                return ('a' if args[1].endswith('recovery-state') else 'b') * 40
            if args[0] == 'show':
                if args[1].startswith('a' * 40):
                    raise subprocess.CalledProcessError(128, ['git', 'show'])
                return json.dumps(cp if '/checkpoints/' in args[1] else record)
            return ''
        with patch.object(loader, '_git', side_effect=fake):
            payload, evidence = loader(record['key'])
        self.assertEqual(evidence['branch'], 'research-fusion-shadow-state')
        self.assertEqual(evidence['remote_sha'], 'b' * 40)
        self.assertEqual(len(payload['baseline_picks']), 10)
        self.assertEqual(sum(x[0] == 'fetch' for x in calls), 1)
        self.assertEqual(len(next(x for x in calls if x[0] == 'fetch')), 6)


class MetricsTests(unittest.TestCase):
    def test_results_are_separate_and_order_alone_never_proves_tactics(self):
        with TemporaryDirectory() as tmp:
            _, f, rec = originals(tmp)
            out = comparison(f, rec, result_for(f, '6-5-4'))
            self.assertFalse(out['actual_tactics_verified'])
            self.assertIsNone(out['official_winner_method'])
            self.assertFalse(any(x['causal_failure_proven'] for x in out['findings']))
            self.assertNotIn('scenario_mismatch', [x['category'] for x in out['findings']])

    def test_refund_void_and_insufficient_data_excluded_with_counts(self):
        with TemporaryDirectory() as tmp:
            _, f, rec = originals(tmp)
            result = result_for(f)
            for change, expected in [({'refund_lanes': [1]}, 'refund'), ({'status': 'void', 'payouts': {}}, 'void'),
                                     ({'status': 'settled', 'payouts': {}}, 'missing_payout')]:
                row = comparison(f, rec, {**result, **change})
                self.assertEqual(row['exclusion_reason'], expected)
                self.assertIsNone(row['hit']); self.assertIsNone(row['stake_yen'])

    def test_daily_denominators_and_unconditional_vs_conditional_metrics(self):
        with TemporaryDirectory() as tmp:
            _, f, rec = originals(tmp)
            save_immutable(Path(tmp) / 'results/20261017' / (f['race_id'] + '.json'), result_for(f))
            before = {str(p): p.read_bytes() for p in Path(tmp).rglob('*.json')}
            one = save_report(tmp, now=NOW + timedelta(hours=2))
            row = next(x for x in one['daily'] if x['ai_id'] == 'venue_16')
            self.assertEqual((row['target_races'], row['predeadline_saved'], row['missing']), (7, 1, 6))
            self.assertEqual((row['graded'], row['virtual_stake_yen'], row['virtual_return_yen']), (1, 1000, 2340))
            self.assertEqual(row['roi_pct'], 234)
            self.assertEqual(row['conditional_third_n'], 1)
            two = save_report(tmp, now=NOW + timedelta(hours=3))
            self.assertEqual(one['digest'], two['digest'])
            for path, content in before.items(): self.assertEqual(Path(path).read_bytes(), content)

    def test_corrupt_receipt_cannot_inflate_save_rate(self):
        with TemporaryDirectory() as tmp:
            _, f, rec = originals(tmp)
            path = Path(tmp) / 'receipts/20261017' / (f['race_id'] + '.json')
            rec['checked_at'] = '2026-10-17T12:00:00+09:00'
            path.write_text(json.dumps(rec))
            out = build_report(tmp, now=NOW + timedelta(hours=2))
            row = next(x for x in out['daily_ai_venue'] if x['ai_id'] == 'venue_16')
            self.assertEqual(row['predeadline_saved'], 0)
            self.assertEqual(row['invalid_originals'], 1)
            self.assertEqual(row['missing'], 7)

    def test_midnight_keeps_previous_missing_and_does_not_claim_seven_days(self):
        with TemporaryDirectory() as tmp:
            originals(tmp)
            now = datetime(2026, 10, 18, 8, 0, tzinfo=JST)
            out = build_report(tmp, now=now)
            self.assertFalse(out['seven_day_gate']['achieved'])
            self.assertEqual(len(out['missing_races']), 13)  # 6 specialist, all 7 Yuuki
            self.assertTrue(all(x['race_id'].startswith('20261017') for x in out['missing_races']))

    def test_two_days_not_accidentally_cumulative_as_one_day(self):
        with TemporaryDirectory() as tmp:
            originals(tmp)
            originals(tmp, day='20261018')
            out = build_report(tmp, now=datetime(2026, 10, 18, 13, tzinfo=JST))
            rows = [r for r in out['daily_ai_venue'] if r['ai_id'] == 'venue_16']
            self.assertEqual([r['predeadline_saved'] for r in rows], [1, 1])
            self.assertEqual([r['target_races'] for r in rows], [7, 7])

    def test_schedule_failure_never_becomes_verified_zero(self):
        with TemporaryDirectory() as tmp:
            inventory = {'day': '20261017', 'schedules': {}, 'errors': [{'venue': '16', 'reason': 'timeout'}]}
            save_immutable(Path(tmp) / 'schedules/20261017/1200.json', inventory)
            report = build_report(tmp, now=NOW + timedelta(hours=2))
            row = next(r for r in report['daily_ai_venue'] if r['ai_id'] == 'venue_16')
            self.assertFalse(row['schedule_verified'])
            self.assertIsNone(row['save_rate_pct'])

    def test_result_from_another_race_or_before_deadline_rejected(self):
        with TemporaryDirectory() as tmp:
            _, f, rec = originals(tmp)
            for change in ({'race_id': '20261017_03_07'}, {'observed_at': '2026-10-17T11:00:00+09:00'}):
                with self.assertRaises(ValueError): comparison(f, rec, {**result_for(f), **change})


class PersistenceResumeTests(unittest.TestCase):
    def _setup(self, tmp):
        root = Path(tmp); bare = root / 'origin.git'; local = root / 'local'
        subprocess.check_call(['git', 'init', '--quiet', '--bare', str(bare)])
        subprocess.check_call(['git', 'clone', '--quiet', str(bare), str(local)], stderr=subprocess.DEVNULL)
        for key, val in [('user.name', 'Test'), ('user.email', 'test@example.invalid')]:
            worker.git(local, 'config', key, val)
        (local / worker.PREFIX).mkdir(parents=True)
        (local / worker.PREFIX / 'seed.json').write_text('{}')
        worker.git(local, 'add', '.')
        worker.git(local, 'commit', '-m', 'seed')
        worker.git(local, 'push', 'origin', 'HEAD:refs/heads/' + worker.BRANCH)
        return local

    def test_unpushed_commit_retries_with_no_new_index_changes(self):
        with TemporaryDirectory() as tmp:
            local = self._setup(tmp)
            (local / worker.PREFIX / 'new_original.json').write_text('{"frozen":true}')
            real = worker.git
            def failing(root, *args):
                if args[0] == 'push': raise subprocess.CalledProcessError(1, ['git', 'push'])
                return real(root, *args)
            with patch.object(worker, 'git', side_effect=failing), self.assertRaises(RuntimeError):
                worker.persist(local, 'freeze', attempts=1, pause=lambda _: None)
            self.assertEqual(real(local, 'diff', '--cached', '--name-only'), '')
            sha = worker.persist(local, 'resume without restaging', pause=lambda _: None)
            self.assertEqual(sha, real(local, 'rev-parse', 'HEAD').strip())
            self.assertIn('true', real(local, 'show', sha + ':' + worker.PREFIX + '/new_original.json'))

    def test_modification_deletion_or_nonresearch_stage_refused(self):
        with TemporaryDirectory() as tmp:
            local = self._setup(tmp)
            (local / worker.PREFIX / 'seed.json').write_text('{"changed":true}')
            with self.assertRaises(ValueError): worker.persist(local, 'illegal overwrite')

    def test_failure_audit_is_local_and_contains_notification_design(self):
        with TemporaryDirectory() as tmp:
            item = worker.failure_event(tmp, RuntimeError('remote unavailable'))
            self.assertIn('no Discord/X', item['notification'])
            self.assertEqual(len(list((Path(tmp) / worker.PREFIX / 'phase1/worker_errors').rglob('*.json'))), 1)

    def test_interrupted_input_can_resume_only_before_cutoff(self):
        with TemporaryDirectory() as tmp:
            snapshot = fixture()
            key = '20261017_16_07'
            path = Path(tmp) / 'inputs/20261017' / (key + '.json')
            save_immutable(path, snapshot)
            original = path.read_bytes()
            out = run.collect_race('20261017', '16', 7, '11:30', tmp, official=FakeOfficial(), clock=lambda: NOW)
            self.assertTrue(out['recovered_partial_input'])
            self.assertEqual(original, path.read_bytes())
        with TemporaryDirectory() as tmp:
            save_immutable(Path(tmp) / 'inputs/20261017' / (key + '.json'), snapshot)
            with self.assertRaises(ValueError):
                run.collect_race('20261017', '16', 7, '11:30', tmp, official=FakeOfficial(), clock=lambda: NOW + timedelta(hours=1))
            self.assertFalse(list((Path(tmp) / 'forecasts').glob('*/*.json')))

    def test_review_resumes_existing_result_without_replacing_it(self):
        from research.venue_specialists_v1 import review
        with TemporaryDirectory() as tmp:
            _, f, _ = originals(tmp)
            dest = Path(tmp) / 'results/20261017' / (f['race_id'] + '.json')
            save_immutable(dest, result_for(f))
            before = dest.read_bytes()
            source = FakeOfficial()
            with patch.object(source, 'fetch', side_effect=AssertionError('No result refetch')):
                report = review.run(tmp, now=NOW + timedelta(hours=2), official=source)
            self.assertEqual(report['new_reviews'], 1)
            self.assertEqual(before, dest.read_bytes())


class PreinspectionTests(unittest.TestCase):
    def _raw(self):
        rows = ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in [str(i), str(4000+i),
            '<a href="https://www.boatrace.jp/?toban=' + str(4000+i) + '">選手</a>',
            'A1', str(i), '40.0%', 'B', str(i), '30.0%', '6.80']) + '</tr>' for i in range(1, 7))
        return '<div class="com-racetitle_group">全日本王者決定戦<dt class="schedule-area__month">10/</dt><span class="item-day">18</span>' + rows

    def test_current_series_matches_racers_and_motors_without_adjustments(self):
        from research.venue_specialists_v1.preinspection import parse, reference
        rows = parse(self._raw(), '23')
        self.assertEqual(len(rows), 6)
        with TemporaryDirectory() as tmp:
            record = {'first_day': '20261018', 'last_day': '20261023', 'rows': rows,
                      'observed_at': NOW.isoformat(), 'source_url': 'official', 'sha256': 'a'*64}
            save_immutable(Path(tmp) / 'phase1/preinspection/20261018/23.json', record)
            boats = fixture('23', '20261018')['boats']
            got = reference(tmp, '23', '20261018', boats, '2026-10-18T10:00:00+09:00')
            self.assertEqual(got['status'], 'six_racer_motor_identities_match')
            self.assertTrue(got['descriptive_only'])
            boats[0]['motor_number'] = 99
            self.assertIn('mismatch', reference(tmp, '23', '20261018', boats, '2026-10-18T10:00:00+09:00')['status'])

    def test_prior_meeting_or_unpublished_page_never_substituted(self):
        from research.venue_specialists_v1.preinspection import parse
        for raw in [self._raw().replace('>18<', '>08<'), '<html>次節開催までしばらくお待ちください</html>']:
            with self.assertRaises(ValueError): parse(raw, '23')

    def test_not_starting_future_hamanako_capture_early(self):
        from research.venue_specialists_v1.preinspection import capture
        source = FakeOfficial()
        # On 10/19 neither configured venue is in its preinspection capture window.
        with TemporaryDirectory() as tmp, patch.object(source, 'fetch', side_effect=AssertionError('No premature fetch')):
            self.assertEqual(capture(tmp, official=source, now=datetime(2026, 10, 19, 12, tzinfo=JST)), [])


if __name__ == '__main__':
    unittest.main()
