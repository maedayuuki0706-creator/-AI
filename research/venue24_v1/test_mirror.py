import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from research.venue24_v1 import engine as e, mirror
from research.venue24_v1.test_engine import fixture


def sample_csv(raw, *, mismatch=False, two_metrics=False):
    labels = ["一周", "まわり足"] if two_metrics else ["一周", "まわり足", "直線"]
    header = ["レースコード", "レース日", "レース場", "レース回",
              "締切時刻", "取得日時", "計測数", "計測項目1", "計測項目2", "計測項目3"]
    for i in range(1, 7):
        header += [f"艇{i}_選手名", f"艇{i}_値1", f"艇{i}_値2", f"艇{i}_値3"]
    code = e.race_id(raw["day"], raw["jcd"], raw["rno"]).replace("_", "")
    values = [code, "2026-10-31", raw["jcd"], f"{raw['rno']:02}R", raw["deadline"],
              "2026-10-31T12:20:00+09:00", str(len(labels))]
    values += labels + [""] * (3 - len(labels))
    for i in range(1, 7):
        name = f"R {i}" if not (mismatch and i == 2) else "違う名前"
        values += [name, "36.4", "5.3", "7.8" if not two_metrics else ""]
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerow(values)
    return stream.getvalue().encode()


class MirrorTests(unittest.TestCase):
    def test_secondary_joins_by_verified_names(self):
        official = e.normalize_official(fixture())
        data, errs = mirror.csv_records(sample_csv(fixture()), [official], "https://source.test/20261031.csv", "2026-11-01T03:00:00+09:00")
        self.assertFalse(errs)
        result = e.join_official_original(fixture(), data[official["race_id"]])
        self.assertEqual(result["original_status"], "retrospective_secondary_source")
        self.assertEqual(result["rows"][0]["original"]["lap_time"], 36.4)
        self.assertFalse(result["original_acquisition"]["scoring_connected"])

    def test_name_mismatch_never_fills_lanes(self):
        official = e.normalize_official(fixture())
        data, errs = mirror.csv_records(sample_csv(fixture(), mismatch=True), [official], "https://source.test/data.csv", "2026-11-01T03:00:00+09:00")
        self.assertFalse(data)
        self.assertEqual(errs[0]["reason"], "racer_name_identity_mismatch")

    def test_two_metric_venue_and_missing_straight(self):
        raw = fixture(code="18")
        official = e.normalize_official(raw)
        data, errs = mirror.csv_records(sample_csv(raw, two_metrics=True), [official], "https://source.test/data.csv", "2026-11-01T03:00:00+09:00")
        self.assertFalse(errs)
        record = e.join_official_original(raw, data[official["race_id"]])
        self.assertIsNone(record["rows"][0]["original"]["straight_time"])
        self.assertEqual(record["rows"][0]["original"]["turn_time"], 5.3)

    def test_official_snapshot_preferred_over_mirror(self):
        from research.venue24_v1.test_engine import original
        raw = fixture()
        primary = original(raw)
        secondary = original(raw)
        secondary["acquisition"]["source_family"] = "BoatraceCSV_secondary"
        secondary["acquisition"]["retrieved_at"] = "2026-10-31T12:40:00+09:00"
        selected = e.find_original([secondary, primary], e.normalize_official(raw))
        self.assertEqual(selected, primary)

    def test_import_is_idempotent_and_source_is_archived(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            official = path / "official" / "20261031"
            official.mkdir(parents=True)
            raw = fixture()
            (official / "23_07.json").write_text(json.dumps(raw, ensure_ascii=False))
            output = path / "mirror"
            source = sample_csv(raw)
            request = lambda _: source
            for _ in range(2):
                summary = mirror.collect(path / "official", output, "20261031", "20261031", request_fn=request)
                self.assertEqual(summary["matched_races"], 1)
            self.assertTrue((output / "source_csv" / "20261031.csv").exists())
            self.assertTrue((output / "normalized" / "20261031_23_07.json").exists())


if __name__ == "__main__":
    unittest.main()
