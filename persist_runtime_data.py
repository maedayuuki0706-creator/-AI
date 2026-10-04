"""Publish runtime snapshots without rebasing or modifying the running checkout.

Build on the current remote head using a temporary Git index. Merge append-only
journals and X receipt sets, then fast-forward with bounded contention retries.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


class PartialCheckpointError(RuntimeError):
    """Critical journals were saved, but independent conflicts need recovery."""

    def __init__(self, paths, saved):
        self.paths = tuple(paths)
        self.saved = saved
        super().__init__(f"Saved {saved} files; unresolved runtime conflicts: {', '.join(paths)}")


def git(*args, data=None, env=None, check=True):
    return subprocess.run(["git", *args], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=check, env=env).stdout


def content(ref, path):
    result = subprocess.run(["git", "show", f"{ref}:{path}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        if git("ls-tree", ref, "--", path).strip():
            raise RuntimeError(f"Cannot read runtime object: {path}")
        return None
    return result.stdout


def merge(path, base, remote, local):
    if remote == local or local == base:
        return remote
    if remote == base:
        return local
    if path.endswith(".jsonl"):
        # Keep remote order, and append distinct local records. Validate first;
        # a broken JSONL must never poison all future deduplication reads.
        rows, seen = [], set()
        for raw in ((remote or b"") + b"\n" + local).splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if canonical not in seen:
                seen.add(canonical)
                rows.append(canonical)
        return ("\n".join(rows) + "\n").encode()
    if path.startswith("data/x_post_delivery/") and path.endswith(".json"):
        from x_delivery_store import merge_state
        return (json.dumps(merge_state(json.loads(remote or b"{}"), json.loads(local)),
                           ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    if path.startswith("data/interim_reports/") and remote is not None:
        return remote  # First published cutoff snapshot is authoritative.
    raise RuntimeError(f"Concurrent runtime update needs review: {path}")


def persist(paths=("data/",), *, exclude=(), attempts=5):
    base_ref = git("rev-parse", "HEAD").decode().strip()
    changed = set(git("diff", "--name-only", "-z", "HEAD", "--", *paths).decode().split("\0"))
    changed.update(git("ls-files", "--others", "--exclude-standard", "-z", "--", *paths).decode().split("\0"))
    changed = sorted(p for p in changed if p and not any(p.startswith(prefix) for prefix in exclude))
    snapshot = {}
    for path in changed:
        if not path.startswith("data/") or not Path(path).is_file() or Path(path).is_symlink():
            raise ValueError(f"Only runtime data files can be checkpointed: {path}")
        snapshot[path] = (content(base_ref, path), Path(path).read_bytes())
    if not snapshot:
        return 0
    for _ in range(attempts):
        git("fetch", "--no-tags", "origin", "main")
        head = git("rev-parse", "FETCH_HEAD").decode().strip()
        with tempfile.TemporaryDirectory(prefix="boat-runtime-index-") as temp:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(temp) / "index"),
                   "GIT_AUTHOR_NAME": "boat-ai-learning-bot", "GIT_COMMITTER_NAME": "boat-ai-learning-bot",
                   "GIT_AUTHOR_EMAIL": "actions@users.noreply.github.com", "GIT_COMMITTER_EMAIL": "actions@users.noreply.github.com"}
            git("read-tree", head, env=env)
            count = 0
            conflicts = []
            for path, (base, local) in snapshot.items():
                remote = content(head, path)
                try:
                    value = merge(path, base, remote, local)
                except (RuntimeError, ValueError):
                    # A derived CSV or mutable research snapshot must never
                    # prevent unrelated delivery journals from being saved.
                    # Leave both versions intact and surface the conflict after
                    # publishing all files that can be merged safely.
                    conflicts.append(path)
                    continue
                if value == remote:
                    continue
                blob = git("hash-object", "-w", "--stdin", data=value).decode().strip()
                git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
                count += 1
            if not count:
                if conflicts:
                    raise PartialCheckpointError(conflicts, 0)
                return 0
            tree = git("write-tree", env=env).decode().strip()
            commit = git("commit-tree", tree, "-p", head, data=b"Checkpoint notification runtime data\n", env=env).decode().strip()
            push = subprocess.run(["git", "push", "origin", f"{commit}:refs/heads/main"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if push.returncode == 0:
                print(f"Runtime checkpoint saved: {count} files", flush=True)
                if conflicts:
                    raise PartialCheckpointError(conflicts, count)
                return count
            # An unrelated writer may advance main between fetch and push.
            # Retry from its new head, never force-push or resolve by deletion.
    raise RuntimeError("Runtime checkpoint could not fast-forward after retries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["data/"])
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()
    persist(tuple(args.paths), exclude=tuple(args.exclude))
