"""Bounded research worker: originals first, verified receipts next, results last."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from . import run, review
from .audit import coverage_counts
from .log_contract import FrozenBaseline, verify_yuuki

BRANCH = 'research-venue-specialists-state'
PREFIX = 'data/venue_specialists_v1'
DERIVED_MUTABLE = {PREFIX + '/summary/latest.json'}


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                   stderr=subprocess.STDOUT, timeout=40)


def _validate_paths(changes, *, prefix=PREFIX, mutable=None):
    mutable = DERIVED_MUTABLE if mutable is None else mutable
    for line in changes.splitlines():
        status, path = line.split('\t', 1)
        if not path.startswith(prefix + '/'):
            raise ValueError('Non-research staged path')
        if status != 'A' and path not in mutable:
            raise ValueError('Immutable research file modification/deletion refused: ' + path)


def _merge_remote(state, remote_sha, *, mutable=None):
    mutable = DERIVED_MUTABLE if mutable is None else mutable
    try:
        git(state, 'merge', '--no-edit', remote_sha)
    except subprocess.CalledProcessError:
        conflicts = git(state, 'diff', '--name-only', '--diff-filter=U').splitlines()
        if not conflicts or not set(conflicts) <= mutable:
            git(state, 'merge', '--abort')
            raise ValueError('Conflicting immutable research originals; refusing overwrite')
        git(state, 'checkout', '--theirs', '--', *conflicts)
        git(state, 'add', '--', *conflicts)
        git(state, 'commit', '--no-edit')


def persist(state, message, *, attempts=3, pause=time.sleep, fusion_pilot_day=None):
    """Retry unpushed commits even with an empty index, without force or overwrites.

    A crash after commit/before push no longer disables the next retry. A remote
    append after our push is accepted if it contains the pushed commit. Every
    returned SHA has been fetched from the remote, not merely read from local HEAD.
    """
    branch, prefix, mutable = BRANCH, PREFIX, DERIVED_MUTABLE
    if fusion_pilot_day is not None:
        # The existing research persister is reused, with a fixed independent
        # branch allowlist. No arbitrary branch/path or production write option.
        from datetime import datetime
        datetime.strptime(fusion_pilot_day, '%Y%m%d')
        branch, prefix = 'research-fusion-recovery-state', 'data/fusion_shadow'
        mutable = {prefix + '/' + x for x in ('heartbeat.json', 'summary.json', 'SUMMARY.md',
                                              'cards/' + fusion_pilot_day + '.json')}
    git(state, 'add', '--', prefix)
    staged = git(state, 'diff', '--cached', '--name-status', '--no-renames')
    _validate_paths(staged, prefix=prefix, mutable=mutable)
    if staged.strip():
        git(state, 'commit', '-m', message)
    for attempt in range(attempts):
        try:
            # Also push when no NEW files were staged: HEAD can contain a
            # commit whose previous push failed or timed out.
            git(state, 'push', 'origin', 'HEAD:refs/heads/' + branch)
        except (subprocess.SubprocessError, OSError):
            pass
        try:
            git(state, 'fetch', '--quiet', '--depth=50', 'origin', 'refs/heads/' + branch)
            remote_sha = git(state, 'rev-parse', 'FETCH_HEAD').strip()
            local_sha = git(state, 'rev-parse', 'HEAD').strip()
            included = remote_sha == local_sha
            if not included:
                try:
                    git(state, 'merge-base', '--is-ancestor', local_sha, remote_sha)
                    included = True
                except subprocess.CalledProcessError:
                    pass
            if included:
                return remote_sha
            _merge_remote(state, remote_sha, mutable=mutable)
        except ValueError:
            raise
        except (subprocess.SubprocessError, OSError):
            pass
        if attempt + 1 < attempts:
            pause(min(2 ** (attempt + 1), 4))
    raise RuntimeError('Research push/remote verification failed after bounded retries; local originals retained')


def tick(state):
    state = Path(state)
    root = state / PREFIX
    from .official import Official
    from .phase1_metrics import save_report
    official = Official()
    baseline = FrozenBaseline(state, run.now_jst)
    collected = run.run(root, max_workers=2, official=official, baseline=baseline)
    # No result request until pre-race originals have been pushed and bound to
    # exact objects read at a fetched remote SHA.
    sha = persist(state, 'research: freeze originals and schedule coverage')
    confirmed_at = run.now_jst()
    show = lambda commit, path: git(state, 'show', f'{commit}:{path}')
    run.verify_commit(root, sha, git_show=show, confirmed_at=confirmed_at)
    verify_yuuki(root, sha, git_show=show, confirmed_at=confirmed_at)
    persist(state, 'research: bind exact remote originals to immutable receipts')
    # Limit result latency to two requests, rather than a backlog of 24.
    reviewed = review.run(root, official=official, max_fetch=2)
    from .preinspection import capture as capture_preinspection
    preinspection = capture_preinspection(root, official=official, now=run.now_jst())
    metrics = save_report(root, now=run.now_jst())
    persist(state, 'research: append official results and Phase 1 comparisons')
    health = coverage_counts(root, collected['day'])
    return {'at': run.now_jst().isoformat(),
            'capture': {k: v for k, v in collected.items() if k != 'elapsed_races_without_confirmed_forecast'},
            'reviews': reviewed, 'coverage': health, 'preinspection': preinspection,
            'phase1_report_digest': metrics['digest'], 'seven_day_gate': metrics['seven_day_gate']}


def failure_event(state, exc):
    from research.scenario_v2.collector import save_immutable
    now = run.now_jst()
    item = {'at': now.isoformat(), 'health': 'error', 'error_type': type(exc).__name__,
            'reason': str(exc)[:300] if not isinstance(exc, subprocess.SubprocessError) else 'Research subprocess failed',
            'retry': 'next_tick_retries_pending_commits_even_without_new_changes',
            'notification': 'Actions error annotation, job summary, failure artifact; no Discord/X send'}
    path = Path(state) / PREFIX / 'phase1/worker_errors' / now.strftime('%Y%m%d/%H%M%S_%f.json')
    save_immutable(path, item)
    return item


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', required=True)
    p.add_argument('--seconds', type=int, default=480)
    p.add_argument('--interval', type=int, default=60)
    a = p.parse_args()
    finish, errors = time.monotonic() + a.seconds, []
    while True:
        start = time.monotonic()
        try:
            local_now = run.now_jst()
            if local_now.hour < 8:
                result = {'at': local_now.isoformat(), 'health': 'idle_outside_hours',
                          'note': 'Official fetch/prediction paused overnight; previous dates reconcile on next active tick'}
            else:
                result = tick(a.state)
        except Exception as exc:
            result = failure_event(a.state, exc)
            errors.append(result)
            print('::error::Independent research persistence/capture error; originals retained for retry', flush=True)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        summary = os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a') as stream:
                stream.write('\n```json\n' + json.dumps(result, ensure_ascii=False) + '\n```\n')
        if time.monotonic() + a.interval >= finish:
            break
        time.sleep(max(1, a.interval - (time.monotonic() - start)))
    if errors:
        raise SystemExit('Research worker encountered errors; see retained originals and per-tick audit')


if __name__ == '__main__':
    main()
