"""Compare-and-swap receipts on discord-delivery-state, never on main."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from delivery_v2 import receipts

BRANCH = 'discord-delivery-state'
API = 'https://api.github.com/repos/maedayuuki0706-creator/-AI'


class Conflict(RuntimeError):
    pass


def _request(path, payload=None, *, method='GET'):
    token = os.getenv('GITHUB_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Durable Discord state requires GITHUB_TOKEN')
    req = urllib.request.Request(API + path, method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'boat-ai-delivery-v2'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def parts(key):
    stream, day, jcd, rno, phase = key.split(':')
    if receipts.identity(stream, day, jcd, rno, phase) != key:
        raise ValueError('Noncanonical receipt identity')
    return stream, day, jcd, int(rno), phase


class GitHubStore:
    def __init__(self):
        self.ready = False

    def ensure(self):
        if self.ready:
            return
        try:
            _request(f'/git/ref/heads/{BRANCH}')
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            head = _request('/git/ref/heads/main')['object']['sha']
            try:
                _request('/git/refs', {'ref': f'refs/heads/{BRANCH}', 'sha': head}, method='POST')
            except urllib.error.HTTPError as race:
                if race.code != 422:
                    raise
                _request(f'/git/ref/heads/{BRANCH}')
        self.ready = True

    @staticmethod
    def path(key):
        stream, day, jcd, rno, phase = parts(key)
        return f'data/delivery_v2_receipts/{day}/{stream}/{jcd}_{rno:02d}_{phase}.json'

    def read(self, key):
        self.ensure()
        try:
            value = _request(f'/contents/{self.path(key)}?ref={BRANCH}')
            row = json.loads(base64.b64decode(value['content']))
            if not isinstance(row, dict) or row.get('key') != key:
                raise ValueError('Invalid durable receipt identity')
            return row, value['sha']
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, None
            raise

    def write(self, key, value, sha):
        self.ensure()
        payload = {'message': f'Discord V2 {key} {value["status"]}', 'branch': BRANCH,
                   'content': base64.b64encode((json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n').encode()).decode()}
        if sha:
            payload['sha'] = sha
        for attempt in range(4):
            try:
                result = _request(f'/contents/{self.path(key)}', payload, method='PUT')
                return result['content']['sha']
            except urllib.error.HTTPError as exc:
                if exc.code not in (409, 422):
                    raise
                current, current_sha = self.read(key)
                if current == value:
                    return current_sha
                if current_sha != sha:
                    raise Conflict('Receipt already changed') from None
                if attempt == 3:
                    raise Conflict('State branch remained busy') from None
                time.sleep(.25 * (attempt + 1))


class FileStore:
    """Offline/test store, with process-safe compare-and-swap."""
    def read(self, key):
        row = receipts.read(*parts(key))
        digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest() if row else None
        return row, digest

    def write(self, key, value, sha):
        import fcntl
        path = receipts.path_for(*parts(key))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current, current_sha = self.read(key)
            if current == value:
                return current_sha
            if current_sha != sha:
                raise Conflict('Receipt already changed')
            receipts.atomic_write(path, value)
            return self.read(key)[1]


def default_store():
    if os.getenv('GITHUB_ACTIONS') == 'true' or os.getenv('GITHUB_TOKEN'):
        return GitHubStore()
    if os.getenv('DELIVERY_V2_LOCAL_TEST') == '1':
        return FileStore()
    raise RuntimeError('Production Discord V2 requires durable state; local mode is test-only')
