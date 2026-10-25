#!/usr/bin/env python3
"""Read-only, rate-limited BOAT RACE official LZH archive acquisition.

Writes only a local output folder (intended for protected GitHub Actions artifacts).
NEVER writes GitHub commits, Sheets, secrets, Render, forecasts, Discord or X.
Run manually in dedicated research CI: python viewer/research/collect_official_lzh.py
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

RACE_HOST = "https://www1.mbrace.or.jp/od2"
RACER_HOST = "https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu"
RACER_PERIODS = {"2026H1": "fan2510.lzh", "2026H2": "fan2604.lzh"}
MAGIC = re.compile(rb"^.{2}-lh[0-7]-", re.S)
MAX_BYTES = 8_000_000


def dates(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def targets(start, end, include_racers=True):
    for d in dates(start, end):
        ym, yy = d.strftime("%Y%m"), d.strftime("%y%m%d")
        for kind, prefix in [("B", "b"), ("K", "k")]:
            yield f"{kind}/{ym}/{prefix}{yy}.lzh", f"{RACE_HOST}/{kind}/{ym}/{prefix}{yy}.lzh"
    if include_racers:
        for period, filename in RACER_PERIODS.items():
            yield f"racers/{period}/{filename}", f"{RACER_HOST}/{filename}"


def download_one(url, path):
    req = Request(url, headers={"User-Agent": "BoatAINavi-Research/1.0 (low-rate personal statistics study)"})
    with urlopen(req, timeout=24) as response:
        status = response.status
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        blob = response.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise ValueError("file exceeds size cap")
    if len(blob) < 25 or not MAGIC.search(blob[:16]):
        raise ValueError("not a verified LZH header")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_bytes(blob)
    os.replace(tmp, path)
    return {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}


def run(args):
    out = Path(args.out)
    if out.resolve() == Path.cwd().resolve():
        raise ValueError("Refusing to store raw archives at repository root")
    out.mkdir(parents=True, exist_ok=True)
    log = []
    target_list = list(targets(args.start, args.end, not args.no_racers))
    if len(target_list) > args.max_requests:
        raise ValueError("Planned downloads exceed explicit per-run max")
    blocked = False
    for index, (relative_path, url) in enumerate(target_list, 1):
        entry = {"path": relative_path, "url": url, "status": "missing", "bytes": 0}
        try:
            if blocked:
                entry["status"] = "not_attempted_provider_block"
            else:
                meta = download_one(url, out / "raw" / relative_path)
                entry.update(meta, status="ok")
        except HTTPError as exc:
            entry.update(status=("missing_404" if exc.code == 404 else f"http_{exc.code}"))
            if exc.code in (403, 429, 503):
                blocked = True
        except (URLError, TimeoutError) as exc:
            entry.update(status="connection_error", error=str(exc)[:160])
        except Exception as exc:
            entry.update(status="invalid_or_unavailable", error=str(exc)[:160])
        log.append(entry)
        if index % 10 == 0:
            print(f"attempted={index}/{len(target_list)} ok={sum(x['status']=='ok' for x in log)}", flush=True)
        if index < len(target_list) and not blocked:
            time.sleep(max(1.5, args.delay))
    statuses = {}
    for entry in log:
        statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1
    manifest = {
        "schema": "boat-navi-official-archive-acquisition-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": args.start.isoformat(), "end": args.end.isoformat(),
        "planned": len(target_list), "statuses": statuses,
        "downloaded_bytes": sum(x["bytes"] for x in log),
        "provider_blocked": blocked,
        "copyright_note": "Official archive files for private research only; never publish or redistribute without permission.",
        "files": log,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("FINAL_MANIFEST_SUMMARY " + json.dumps({k: v for k, v in manifest.items() if k != "files"}, ensure_ascii=False), flush=True)
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 24))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 23))
    p.add_argument("--out", default="/tmp/boat-navi-history-acquisition")
    p.add_argument("--delay", type=float, default=1.6)
    p.add_argument("--max-requests", type=int, default=90)
    p.add_argument("--no-racers", action="store_true")
    args = p.parse_args()
    if args.start > args.end or (args.end - args.start).days > 180:
        p.error("Date range must be 1 to 181 days")
    run(args)


if __name__ == "__main__":
    main()
