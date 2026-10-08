import csv
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import persist_runtime_data as runtime


class RuntimePersistenceTests(unittest.TestCase):
    def test_merge_keeps_both_x_receipts_instead_of_git_conflict(self):
        base = b'{"x_posted_races":[]}'
        a = b'{"x_posted_races":["A"],"x_post_ids":{"A":"1"}}'
        b = b'{"x_posted_races":["B"],"x_post_ids":{"B":"2"}}'
        value = json.loads(runtime.merge('data/x_post_delivery/20261003.json', base, a, b))
        self.assertEqual(value['x_posted_races'], ['A','B'])
        self.assertEqual(value['x_post_ids'], {'A':'1','B':'2'})

    def test_append_only_journals_keep_concurrent_rows_and_deduplicate(self):
        result = runtime.merge('data/hit_alert_deliveries.jsonl', b'{"key":"0"}\n',
                               b'{"key":"0"}\n{"key":"A"}\n', b'{"key":"0"}\n{"key":"B"}\n')
        self.assertEqual([json.loads(line)['key'] for line in result.splitlines()], ['0','A','B'])

    def test_exhibition_csv_merges_disjoint_changes_and_multiline_parts(self):
        header = ["日付", "場", "R", "枠"] + [f"column{i}" for i in range(18)]
        row = ["2026/10/08", "桐生", "2", "3"] + [""] * 18
        row[5] = "6.81"
        def csv_bytes(*data):
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(data)
            return buffer.getvalue().encode("utf-8")
        base = csv_bytes(row)
        remote = row.copy()
        remote[17] = "0.13"  # A newly confirmed race-start result
        local = row.copy()
        local[16] = "リング×2\nシリンダ"  # Quoted multiline part replacement
        new = ["2026/10/08", "桐生", "2", "4"] + [""] * 18
        new[5] = "6.83"
        merged = runtime.merge("data/exhibition_log/recent.csv", base,
                               csv_bytes(remote), csv_bytes(local, new))
        result = list(csv.reader(io.StringIO(merged.decode("utf-8"), newline="")))
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1][17], "0.13")
        self.assertEqual(result[1][16], "リング×2\nシリンダ")
        self.assertEqual(result[2][:4], new[:4])

    def test_exhibition_csv_conflicting_field_still_fails_closed(self):
        header = "日付,場,R,枠,選手," + ",".join(f"column{i}" for i in range(17))
        base = (header + "\n2026/10/08,桐生,2,3,選手A" + "," * 17 + "\n").encode()
        remote = base.replace("選手A".encode(), "選手B".encode())
        local = base.replace("選手A".encode(), "選手C".encode())
        with self.assertRaises(RuntimeError):
            runtime.merge("data/exhibition_log/recent.csv", base, remote, local)

    def test_conflicting_unknown_document_is_not_overwritten(self):
        with self.assertRaises(RuntimeError):
            runtime.merge('data/unknown.json', b'{}', b'{"a":1}', b'{"b":2}')

    def test_publish_after_remote_advance_keeps_checkout_and_both_writers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = {**os.environ, 'GIT_AUTHOR_NAME':'test','GIT_COMMITTER_NAME':'test',
                   'GIT_AUTHOR_EMAIL':'test@example.test','GIT_COMMITTER_EMAIL':'test@example.test'}
            def git(cwd, *args):
                return subprocess.run(['git',*args], cwd=cwd, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
            origin = root/'origin.git'
            git(root, 'init','--bare','--initial-branch=main',str(origin))
            local = root/'worker'
            git(root, 'clone',str(origin),str(local))
            (local/'data/x_post_delivery').mkdir(parents=True)
            (local/'data/hits.jsonl').write_text('{"key":"0"}\n')
            (local/'data/recent.csv').write_text('initial\n')
            (local/'data/x_post_delivery/state.json').write_text('{"x_posted_races":[]}')
            git(local,'add','data')
            git(local,'commit','-m','initial')
            git(local,'push','origin','main')
            other=root/'other'
            git(root,'clone',str(origin),str(other))
            (other/'data/x_post_delivery/state.json').write_text('{"x_posted_races":["A"]}')
            (other/'data/hits.jsonl').write_text('{"key":"0"}\n{"key":"A"}\n')
            (other/'data/recent.csv').write_text('remote\n')
            git(other,'add','data')
            git(other,'commit','-m','other writer')
            git(other,'push','origin','main')
            (local/'data/x_post_delivery/state.json').write_text('{"x_posted_races":["B"]}')
            (local/'data/hits.jsonl').write_text('{"key":"0"}\n{"key":"B"}\n')
            (local/'data/recent.csv').write_text('local\n')
            before = git(local,'rev-parse','HEAD')
            original_dir = Path.cwd()
            try:
                os.chdir(local)
                with self.assertRaises(runtime.PartialCheckpointError) as first:
                    runtime.persist()
                self.assertEqual(first.exception.saved, 2)
                self.assertEqual(first.exception.paths, ('data/recent.csv',))
                with self.assertRaises(runtime.PartialCheckpointError) as second:
                    runtime.persist()
                self.assertEqual(second.exception.saved, 0)
            finally:
                os.chdir(original_dir)
            self.assertEqual(git(local,'rev-parse','HEAD'),before)
            self.assertFalse((local/'.git/rebase-merge').exists())
            self.assertEqual((local/'data/recent.csv').read_text(), 'local\n')
            self.assertEqual(git(root,'--git-dir',str(origin),'show','main:data/recent.csv'), b'remote\n')
            state=json.loads(git(root,'--git-dir',str(origin),'show','main:data/x_post_delivery/state.json'))
            self.assertEqual(state['x_posted_races'],['A','B'])
            journal=git(root,'--git-dir',str(origin),'show','main:data/hits.jsonl')
            self.assertEqual([json.loads(line)['key'] for line in journal.splitlines()],['0','A','B'])


if __name__ == '__main__':
    unittest.main()
