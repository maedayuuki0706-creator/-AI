"""Compare-and-swap receipts on discord-delivery-state, never on main."""
from __future__ import annotations
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from delivery_v2 import receipts

BRANCH = 'discord-delivery-state'
API = 'https://api.github.com/repos/maedayuuki0706-creator/-AI'
RAW = 'https://raw.githubusercontent.com/maedayuuki0706-creator/-AI'


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
        self.confirmed = {}
        self.blobs = {}

    def remember(self, key, row, sha):
        # Only an acknowledged send is immutable. Claims, retries and absence
        # must always be read afresh before compare-and-swap.
        if row.get('status') == 'sent' and str(row.get('message_id', '')).isdigit():
            self.confirmed[key] = deepcopy(row), sha

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
        if key in self.confirmed:
            return deepcopy(self.confirmed[key])
        self.ensure()
        try:
            value = _request(f'/contents/{self.path(key)}?ref={BRANCH}')
            row = json.loads(base64.b64decode(value['content']))
            if not isinstance(row, dict) or row.get('key') != key:
                raise ValueError('Invalid durable receipt identity')
            self.remember(key, row, value['sha'])
            return row, value['sha']
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, None
            raise

    def list_day(self, day):
        """Pinned, hash-checked snapshot without one REST call per receipt."""
        receipts.identity('main', day, '01', 1)
        self.ensure()
        head = _request(f'/git/ref/heads/{BRANCH}')['object']['sha']
        tree = _request(f'/git/trees/{head}?recursive=1')
        if tree.get('truncated'):
            raise RuntimeError('State tree is truncated; delivery audit is incomplete')
        prefix = f'data/delivery_v2_receipts/{day}/'
        def load(entry):
            path = entry['path']
            sha = entry['sha']
            if sha not in self.blobs:
                # This public repository's raw commit files require no token.
                # A pinned SHA and Git blob hash prevent stale CDN content from
                # becoming permission to resend. Authenticated reads remain
                # the fallback if a newly published raw file is unavailable.
                try:
                    url = RAW + '/' + head + '/' + quote(path, safe='/')
                    with urllib.request.urlopen(url, timeout=20) as response:
                        data = response.read()
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
                    data = base64.b64decode(_request('/git/blobs/' + sha)['content'])
                except urllib.error.URLError:
                    data = base64.b64decode(_request('/git/blobs/' + sha)['content'])
                digest = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                if digest != sha:
                    raise ValueError('State snapshot blob hash mismatch')
                self.blobs[sha] = data
            row = json.loads(self.blobs[sha])
            if not isinstance(row, dict) or self.path(row.get('key', '')) != path:
                raise ValueError('Invalid receipt in state snapshot')
            self.remember(row['key'], row, sha)
            return row['key'], row
        entries = [entry for entry in tree.get('tree', []) if entry['type'] == 'blob'
                   and entry['path'].startswith(prefix) and entry['path'].endswith('.json')]
        with ThreadPoolExecutor(max_workers=4) as pool:
            return dict(pool.map(load, entries))

    def write(self, key, value, sha):
        self.ensure()
        self.confirmed.pop(key, None)
        payload = {'message': f'Discord V2 {key} {value["status"]}', 'branch': BRANCH,
                   'content': base64.b64encode((json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n').encode()).decode()}
        if sha:
            payload['sha'] = sha
        for attempt in range(4):
            try:
                result = _request(f'/contents/{self.path(key)}', payload, method='PUT')
                saved_sha = result['content']['sha']
                self.remember(key, value, saved_sha)
                return saved_sha
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

    def list_day(self, day):
        receipts.identity('main', day, '01', 1)
        result = {}
        for path in (receipts.ROOT / day).glob('*/*.json'):
            row = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(row, dict) or receipts.path_for(*parts(row.get('key', ''))) != path:
                raise ValueError('Invalid receipt in state snapshot')
            result[row['key']] = row
        return result

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
