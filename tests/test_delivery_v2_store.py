import base64
import hashlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from delivery_v2 import store as state


class GitHubSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.key = 'yuuki:20261005:23:7:final'
        self.row = {'key': self.key, 'status': 'sent', 'message_id': '12345'}
        self.data = json.dumps(self.row).encode()
        self.sha = hashlib.sha1(b'blob '+str(len(self.data)).encode()+b'\0'+self.data).hexdigest()
        self.head = 'a'*40
        self.path = state.GitHubStore.path(self.key)
        self.store = state.GitHubStore()
        self.store.ready = True
        self.tree = {'tree': [{'type': 'blob', 'path': self.path, 'sha': self.sha}]}

    def request(self, path, *args, **kwargs):
        if path == '/git/ref/heads/'+state.BRANCH:
            return {'object': {'sha': self.head}}
        if path == '/git/trees/'+self.head+'?recursive=1':
            return self.tree
        if path == '/git/blobs/'+self.sha:
            return {'content': base64.b64encode(self.data).decode()}
        raise AssertionError('Unexpected authenticated API read: '+path)

    def test_pinned_snapshot_reuses_blobs_and_confirmed_receipts_without_rest_per_file(self):
        with patch.object(state, '_request', side_effect=self.request) as api, \
             patch.object(state.urllib.request, 'urlopen', return_value=io.BytesIO(self.data)) as raw:
            self.assertEqual(self.store.list_day('20261005')[self.key], self.row)
            raw.assert_called_once_with(state.RAW+'/'+self.head+'/'+self.path, timeout=20)
            # Fresh ref/tree, but the immutable blob is already available.
            self.store.list_day('20261005')
            raw.assert_called_once()
            self.assertEqual(api.call_count, 4)
            cached, _ = self.store.read(self.key)
            cached['status'] = 'mutated'
            self.assertEqual(self.store.read(self.key)[0], self.row)
            self.assertEqual(api.call_count, 4)

    def test_corrupt_raw_data_fails_closed_without_caching_or_authorizing_a_send(self):
        with patch.object(state, '_request', side_effect=self.request), \
             patch.object(state.urllib.request, 'urlopen', return_value=io.BytesIO(b'{}')):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                self.store.list_day('20261005')
        self.assertFalse(self.store.confirmed)

    def test_new_raw_file_404_uses_authenticated_blob_and_checks_hash(self):
        absent = HTTPError('redacted', 404, 'not propagated', {}, None)
        with patch.object(state, '_request', side_effect=self.request) as api, \
             patch.object(state.urllib.request, 'urlopen', side_effect=absent):
            self.assertEqual(self.store.list_day('20261005')[self.key], self.row)
            self.assertEqual(api.call_args.args[0], '/git/blobs/'+self.sha)

    def test_hash_valid_but_wrong_receipt_identity_is_rejected(self):
        self.tree['tree'][0]['path'] = self.path.replace('23_07', '23_08')
        with patch.object(state, '_request', side_effect=self.request), \
             patch.object(state.urllib.request, 'urlopen', return_value=io.BytesIO(self.data)):
            with self.assertRaisesRegex(ValueError, 'Invalid receipt'):
                self.store.list_day('20261005')
        self.assertFalse(self.store.confirmed)

    def test_mutable_claims_and_missing_ack_are_never_cached(self):
        for row in [{'key': self.key, 'status': 'sending'},
                    {'key': self.key, 'status': 'sent'},
                    {'key': self.key, 'status': 'uncertain'}]:
            self.store.remember(self.key, row, 'old')
        response = {'content': base64.b64encode(json.dumps(self.row).encode()).decode(), 'sha': self.sha}
        with patch.object(state, '_request', return_value=response) as api:
            self.assertEqual(self.store.read(self.key)[0]['message_id'], '12345')
            api.assert_called_once()

    def test_retry_claim_is_reread_before_observing_another_workers_ack(self):
        retry = {'key': self.key, 'status': 'retry', 'attempt': 1}
        replies = [{'content': base64.b64encode(json.dumps(row).encode()).decode(), 'sha': sha}
                   for row, sha in [(retry, 'old'), (self.row, self.sha)]]
        with patch.object(state, '_request', side_effect=replies) as api:
            self.assertEqual(self.store.read(self.key)[0]['status'], 'retry')
            self.assertEqual(self.store.read(self.key)[0]['status'], 'sent')
            self.assertEqual(api.call_count, 2)

    def test_truncated_tree_is_never_accepted_as_complete(self):
        self.tree['truncated'] = True
        with patch.object(state, '_request', side_effect=self.request), \
             patch.object(state.urllib.request, 'urlopen') as raw:
            with self.assertRaisesRegex(RuntimeError, 'truncated'):
                self.store.list_day('20261005')
            raw.assert_not_called()


if __name__ == '__main__':
    unittest.main()
