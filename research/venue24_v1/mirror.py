"""Read-only, bounded import of public BoatraceCSV original exhibition snapshots.

This is a secondary archive, not proof the numbers were accessible to our
forecast before deadline. ALL source CSV and normalized rows retain provenance.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import io
import json
import re
import time
import urllib.error
import urllib.request

from . import engine

BASE = "https://boatracecsv.github.io/data/previews/original_exhibition/"
ALIASES = {
    "一周": "lap_time", "1周": "lap_time", "１周": "lap_time",
    "半周": "half_lap_time", "半周ラップ": "half_lap_time",
    "まわり足": "turn_time", "回り足": "turn_time",
    "直線": "straight_time",
}
MAX_BYTES = 2_000_000


def plain_name(name):
    return re.sub(r"[\s\u3000]+", "", str(name or ""))


def csv_records(content, official, source_url, downloaded_at):
    """Name equality is compulsory because the CSV does not carry racer IDs."""
    raw_sha = sha256(content).hexdigest()
    output, errors = {}, []
    official_by_key = {r["race_id"]: r for r in official}
    try:
        lines = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        for line in lines:
            raw_key = str(line.get("レースコード") or "")
            if not re.fullmatch(r"\d{12}", raw_key):
                errors.append({"race_id": raw_key, "reason": "invalid_race_code"})
                continue
            key = f"{raw_key[:8]}_{raw_key[8:10]}_{raw_key[10:12]}"
            target = official_by_key.get(key)
            if target is None:
                continue
            if key in output:
                errors.append({"race_id": key, "reason": "duplicate_race_code"})
                output.pop(key, None)
                continue
            code = target["venue_code"]
            if not engine.VENUES[code]["original_supported"]:
                continue
            labels = [str(line.get("計測項目" + str(n)) or "").strip() for n in (1, 2, 3)]
            count = int(line.get("計測数") or 0)
            if count not in (2, 3) or any(label not in ALIASES for label in labels[:count]):
                errors.append({"race_id": key, "reason": "unrecognized_metric_schema"})
                continue
            mapping = [ALIASES[label] for label in labels[:count]]
            if len(set(mapping)) != count or not set(mapping).issubset(engine.VENUES[code]["expected_metrics"]):
                errors.append({"race_id": key, "reason": "metric_not_expected_for_venue"})
                continue
            rows = []
            mismatch = False
            for i, official_row in enumerate(target["rows"], 1):
                source_name = line.get(f"艇{i}_選手名")
                if plain_name(source_name) != plain_name(official_row["racer_name"]):
                    mismatch = True
                    break
                entry = {
                    "lane": i,
                    "racer_id": official_row["racer_id"],
                    "motor_number": official_row["motor_number"],
                }
                for pos, metric in enumerate(mapping, 1):
                    entry[metric] = engine.positive_number(line.get(f"艇{i}_値{pos}"), 2, 80)
                rows.append(entry)
            if mismatch:
                errors.append({"race_id": key, "reason": "racer_name_identity_mismatch"})
                continue
            if all(all(b.get(metric) is None for metric in mapping) for b in rows):
                errors.append({"race_id": key, "reason": "all_measurements_missing"})
                continue
            data = {
                "race_id": key, "status": "ok",
                "usage": "retrospective_secondary_archive_only",
                "acquisition": {
                    "source_family": "BoatraceCSV_secondary",
                    "url": source_url, "sha256": raw_sha,
                    "retrieved_at": line.get("取得日時"),
                    "downloaded_at": downloaded_at,
                    "published_at": None,
                    "identity_enriched_from": "own_official_exhibition_log_by_exact_lane_and_name",
                },
                "rows": rows,
            }
            normalized, reason = engine.normalize_original(data, target)
            if normalized is None:
                errors.append({"race_id": key, "reason": reason})
                continue
            output[key] = data
    except (UnicodeDecodeError, csv.Error, ValueError, TypeError) as exc:
        raise ValueError("Invalid secondary CSV archive: " + str(exc)) from exc
    return output, errors


def download_csv(day, destination, request_fn=None):
    """One GET per missing calendar day. No race-by-race polling."""
    datetime.strptime(day, "%Y%m%d")
    dest = Path(destination)
    if dest.exists():
        return dest.read_bytes(), "cached"
    url = BASE + f"{day[:4]}/{day[4:6]}/{day[6:]}.csv"
    if request_fn is None:
        def request_fn(address):
            req = urllib.request.Request(address, headers={
                "User-Agent": "BoatAI-venue24-research/1.0",
                "Accept": "text/csv",
            })
            with urllib.request.urlopen(req, timeout=20) as response:
                if response.url != address:
                    raise ValueError("Unexpected source redirect")
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("Secondary CSV size exceeded")
                return data
    content = request_fn(url)
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Invalid secondary CSV size")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as fp:
        fp.write(content)
    return content, "downloaded"


def collect(official_dir, output_dir, start_day, end_day, *, request_fn=None):
    """Archive source CSV and normalized snapshots only, not model score updates."""
    if start_day > end_day:
        raise ValueError("Start after end")
    start = datetime.strptime(start_day, "%Y%m%d").date()
    end = datetime.strptime(end_day, "%Y%m%d").date()
    if (end - start).days > 90:
        raise ValueError("Limit secondary backfill to at most 91 calendar days")
    official = engine.build_records(official_dir, through=end_day)
    out = Path(output_dir)
    day = start
    summary = {"day_count": 0, "source_dates_available": 0, "matched_races": 0,
               "rejected": 0, "source": BASE, "retrospective_only": True}
    while day <= end:
        text_day = day.strftime("%Y%m%d")
        url = BASE + f"{text_day[:4]}/{text_day[4:6]}/{text_day[6:]}.csv"
        try:
            content, status = download_csv(text_day, out / "source_csv" / (text_day + ".csv"), request_fn)
            manifest_path = out / "manifests" / (text_day + ".json")
            archived_at = (json.loads(manifest_path.read_text())["archived_at"]
                           if manifest_path.exists() else datetime.now().astimezone().isoformat())
            records, errors = csv_records(content, official, url, archived_at)
            for key, record in records.items():
                engine.immutable_json(out / "normalized" / (key + ".json"), record)
            engine.immutable_json(manifest_path, {
                "day": text_day, "source_url": url,
                "raw_sha256": sha256(content).hexdigest(),
                "valid_races": sorted(records),
                "invalid": errors,
                "archived_at": archived_at,
            })
            summary["source_dates_available"] += 1
            summary["matched_races"] += len(records)
            summary["rejected"] += len(errors)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as exc:
            summary.setdefault("missing_dates", []).append({"day": text_day, "reason": type(exc).__name__})
        summary["day_count"] += 1
        day += timedelta(days=1)
        if request_fn is None and day <= end:
            time.sleep(0.25)
    return summary


def main():
    p = argparse.ArgumentParser(description="Read-only 23-venue secondary original exhibition importer")
    p.add_argument("--official-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    args = p.parse_args()
    print(json.dumps(collect(args.official_dir, args.out, args.start, args.end), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
