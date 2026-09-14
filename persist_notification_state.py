"""Merge data on fresh main, then push without force; never rebase a live sender."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import notification_audit as audit


class PersistenceError(RuntimeError):
    pass


def git(*args, data=None, env=None, check=True):
    result = subprocess.run(['git', *args], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, timeout=35)
    if check and result.returncode:
        # Git stderr can contain credentials from a remote URL.
        raise PersistenceError('Git operation failed: ' + args[0])
    return result


def merge_content(path, remote, local, base=b''):
    if path.endswith('.jsonl'):
        rows, seen = [], set()
        for content in (remote, local):
            for line in content.decode().splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                key = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                if key not in seen:
                    seen.add(key)
                    rows.append(json.dumps(obj, ensure_ascii=False, sort_keys=True))
        return ('\n'.join(rows) + ('\n' if rows else '')).encode()
    if not remote or remote == base or remote == local:
        return local
    if '/notification_outbox/' in path:
        a, b = json.loads(remote), json.loads(local)
        if a.get('status') == 'confirmed':
            if b.get('status') == 'confirmed' and a.get('message_id') != b.get('message_id'):
                raise PersistenceError('Conflicting Discord acknowledgements')
            return remote
        if a.get('run_id') != b.get('run_id'):
            raise PersistenceError('Another run owns this pending delivery')
        return local
    if '/race_cards/' in path:
        a, b = json.loads(remote), json.loads(local)
        newer, older = (b, a) if b.get('checked_at', '') >= a.get('checked_at', '') else (a, b)
        races = dict(older.get('races', {}))
        for key, value in newer.get('races', {}).items():
            if value.get('deadline') or key not in races:
                races[key] = value
        return (json.dumps({**newer, 'races': races}, ensure_ascii=False, indent=2) + '\n').encode()
    raise PersistenceError('Concurrent change to ' + path)


def changed_data():
    tracked = git('diff', '--name-only', 'HEAD', '--', 'data/').stdout.decode().splitlines()
    new = git('ls-files', '--others', '--exclude-standard', '--', 'data/').stdout.decode().splitlines()
    return {path: Path(path).read_bytes() for path in set(tracked + new) if Path(path).is_file()}


def publish(snapshot, *, retries=5, before_push=None):
    if not snapshot:
        return None
    base = {}
    for path in snapshot:
        result = git('show', 'HEAD:' + path, check=False)
        base[path] = result.stdout if result.returncode == 0 else b''
    for attempt in range(retries):
        git('fetch', '--quiet', 'origin', 'main')
        parent = git('rev-parse', 'origin/main').stdout.decode().strip()
        merged = {}
        with tempfile.TemporaryDirectory(prefix='boat-ai-index-') as directory:
            env = {**os.environ, 'GIT_INDEX_FILE': str(Path(directory) / 'index'),
                   'GIT_AUTHOR_NAME': 'boat-ai-learning-bot', 'GIT_AUTHOR_EMAIL': 'actions@users.noreply.github.com',
                   'GIT_COMMITTER_NAME': 'boat-ai-learning-bot', 'GIT_COMMITTER_EMAIL': 'actions@users.noreply.github.com'}
            git('read-tree', parent, env=env)
            for path, local in snapshot.items():
                result = git('show', parent + ':' + path, check=False)
                remote = result.stdout if result.returncode == 0 else b''
                merged[path] = merge_content(path, remote, local, base[path])
                blob = git('hash-object', '-w', '--stdin', data=merged[path]).stdout.decode().strip()
                git('update-index', '--add', '--cacheinfo', '100644', blob, path, env=env)
            tree = git('write-tree', env=env).stdout.decode().strip()
            if tree == git('rev-parse', parent + '^{tree}').stdout.decode().strip():
                for path, content in merged.items():
                    Path(path).write_bytes(content)
                return None
            commit = git('commit-tree', tree, '-p', parent, env=env,
                         data=b'Persist notification evidence and delivery state\n').stdout.decode().strip()
            if before_push:
                before_push(attempt)
            pushed = git('push', '--quiet', 'origin', commit + ':refs/heads/main', check=False)
            if pushed.returncode == 0:
                for path, content in merged.items():
                    Path(path).write_bytes(content)
                return commit
        if attempt + 1 < retries:
            time.sleep(.5 * (attempt + 1))
    raise PersistenceError('Repository persistence did not succeed after retries')


def checkpoint(*, required=False):
    if os.getenv('NOTIFICATION_CHECKPOINT') != '1':
        return None
    try:
        snapshot = changed_data()
        commit = publish(snapshot)
        if commit:
            deliveries = []
            for path, content in snapshot.items():
                if '/notification_outbox/' in path:
                    obj = json.loads(content)
                    if obj.get('status') == 'confirmed':
                        deliveries.extend({key: row.get(key) for key in ('day', 'jcd', 'rno', 'phase', 'message_id')}
                                          for row in obj.get('records', []))
            audit.emit('persist_success', scope='repository', commit_sha=commit, deliveries=deliveries)
            # This refers to the data commit already accepted by GitHub.
            publish(changed_data())
        return commit
    except Exception as exc:
        audit.emit('persist_failed', scope='repository', error_type=type(exc).__name__)
        if required:
            raise PersistenceError('Cannot durably record notification state') from None
        return False


if __name__ == '__main__':
    os.environ['NOTIFICATION_CHECKPOINT'] = '1'
    checkpoint(required=True)
