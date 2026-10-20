"""Result-free, six-boat use of acquired materials; no network or live writes.

The unchanged main engine already accepts shrunken course profiles. Scenario
v2 already accepts straight/turn/lap measurements. This adapter supplies those
missing inputs and records the provenance and exact card changes.
"""
from __future__ import annotations

import base64
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path

from prediction_engine import analyze_race
from racer_profiles import COURSE_PRIORS, _smoothed_rate
from research.materials_v1.supplement import karatsu_foot
from research.scenario_v2 import engine as scenario
from research.venue_fusion_v1.official_program import from_frozen_official
from research.venue_fusion_v1 import engine as hybrid

VERSION = "materials-applied-main-and-six-boat-v1"


def clock():
    return datetime.now(scenario.JST).isoformat()


def read_json(path):
    path = Path(path)
    data = path.read_bytes()
    if path.suffix == ".b64":
        data = base64.b64decode(data, validate=False)
    if path.suffix == ".gz" or path.name.endswith(".gz.b64"):
        data = gzip.decompress(data)
    return json.loads(data)


def _count(value):
    return scenario.integer(value, 0, 10**7)


class Materials:
    """Read only the two acquired history files, never current race results.

    Dates are filtered per target race. No all-period rate is used to predict
    an earlier race. Retrospective acquisition remains explicitly labelled.
    """

    def __init__(self, root, *, loaded_at=None):
        self.root = Path(root).resolve()
        self.loaded_at = loaded_at or clock()
        self.course_rows = {}
        self.context_rows = {}
        self.histories = defaultdict(list)
        self.motor_histories = defaultdict(list)
        self.sources = {}
        self.latest_history_observed_at = None
        for name in ("racer_tendencies", "motor_race_histories"):
            candidates = [self.root / "derived" / (name + ext)
                          for ext in (".json.gz.b64", ".json.gz", ".json")]
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                raise ValueError("Missing acquired material: " + name)
            rows = read_json(path)
            if not isinstance(rows, list):
                raise ValueError("History must contain explicit rows")
            self.sources[name] = {"file": str(path.relative_to(self.root)),
                                  "sha256": sha256(path.read_bytes()).hexdigest(),
                                  "rows": len(rows)}
            if name == "racer_tendencies":
                for row in rows:
                    key = (str(row["racer_id"]), row["dimension"], str(row["group"]))
                    if key in self.context_rows:
                        raise ValueError("Duplicate racer condition")
                    self.context_rows[key] = row
                    if row["dimension"] == "course":
                        self.course_rows[(key[0], key[2])] = row
            else:
                seen = set()
                for row in rows:
                    key = (row["race_id"], int(row["lane"]))
                    if key in seen:
                        raise ValueError("Duplicate history observation")
                    seen.add(key)
                    self.histories[str(row["racer_id"])].append(row)
                    if row.get('observed_at'):
                        observed = scenario.aware(row['observed_at'])
                        if self.latest_history_observed_at is None or observed > self.latest_history_observed_at:
                            self.latest_history_observed_at = observed
                    self.motor_histories[(str(row["venue_code"]).zfill(2),
                                          int(row["motor_number"]))].append(row)

    def profile(self, racer, course, target_day):
        day = datetime.strptime(target_day, "%Y%m%d").date().isoformat()
        row = self.course_rows.get((str(racer), str(course)))
        if row and row["period_end"] < day:
            result = deepcopy(row)
            n = _count(result["denominator"])
            wins, top2, top3 = (_count(result[k]) for k in ("wins", "top2_count", "top3_count"))
            if not 0 <= wins <= top2 <= top3 <= n:
                raise ValueError("Impossible historical counts")
            methods = result.get("winning_methods", {})
            if sum(_count(v) for v in methods.values()) > wins:
                raise ValueError("Method counts exceed historical wins")
            result["methods_known"] = True
            return result
        # A later aggregate is not permissible for an earlier target. Rebuild
        # counts strictly from earlier days and leave unavailable methods blank.
        earlier = [r for r in self.histories[str(racer)]
                   if r["day"] < day and int(r["actual_course"]) == int(course)]
        sts = [float(r["actual_st"]) for r in earlier
               if r.get("actual_st") is not None and 0 <= float(r["actual_st"]) <= 1]
        return {"racer_id": str(racer), "denominator": len(earlier),
                "wins": sum(r["finish"] == 1 for r in earlier),
                "top2_count": sum(r["finish"] <= 2 for r in earlier),
                "top3_count": sum(r["finish"] <= 3 for r in earlier),
                "mean_actual_st": sum(sts) / len(sts) if sts else None,
                "st_denominator": len(sts), "winning_methods": {}, "methods_known": False,
                "period_start": min((r["day"] for r in earlier), default=None),
                "period_end": max((r["day"] for r in earlier), default=None),
                "sample_status": "small_sample" if len(earlier) < 30 else "descriptive_only"}

    def motor_context(self, venue, number, target_day):
        """Describe each machine generation separately; never infer continuity."""
        day = datetime.strptime(target_day, "%Y%m%d").date().isoformat()
        groups = defaultdict(list)
        for row in self.motor_histories[(str(venue).zfill(2), int(number))]:
            if row["day"] < day and row.get("cycle_id"):
                groups[row["cycle_id"]].append(row)
        return {"current_cycle_verified": False, "model_fields_applied": [],
                "reason": "Current motor period must be rechecked; no second motor-rate bonus",
                "separate_periods": [
                    {"cycle_id": key, "starts": len(rows),
                     "top2_count": sum(r["finish"] <= 2 for r in rows),
                     "top3_count": sum(r["finish"] <= 3 for r in rows),
                     "last_race_day": max(r["day"] for r in rows)}
                    for key, rows in sorted(groups.items())]}


def _apply_profile(boat, profile, *, prior_control=False):
    """Same prior, smoothing, minimum count and ST blend as racer_profiles.

    The explicit prior-only control distinguishes real data effects from
    filling the official-only core's previously missing course defaults.
    """
    course = int(boat.get("predicted_course") or boat["lane"])
    prior = COURSE_PRIORS[course]
    n = profile["denominator"]
    fields = {}
    for key, successes, base in (("course_win_rate", "wins", "win"),
                                 ("course_top2_rate", "top2_count", "top2")):
        if boat.get(key) is not None:
            continue
        value = prior[base]
        if not prior_control and n >= 3:
            value = _smoothed_rate(profile[successes], n, prior[base])
        fields[key] = round(value, 2)
    if not prior_control:
        fields["course_history_samples"] = n
        average = profile.get("mean_actual_st")
        if average is not None:
            fields["course_history_avg_st"] = scenario.number(average, 0, 1)
        if profile.get("methods_known") and n:
            methods = profile["winning_methods"]
            if course == 1:
                fields["in_escape_rate"] = round(100 * methods.get("逃げ", 0) / n, 2)
            else:
                for method, field in (("差し", "course_sashi_rate"),
                                      ("まくり", "course_makuri_rate"),
                                      ("まくり差し", "course_makurisashi_rate")):
                    fields[field] = round(100 * methods.get(method, 0) / n, 2)
                fields["course_attack_rate"] = round(100 * sum(
                    methods.get(k, 0) for k in ("差し", "まくり", "まくり差し")) / n, 2)
    boat.update(fields)
    return fields


def load_foot(root, snapshot, *, mode, at):
    """Verify original raw HTML + date + six identities before joining times."""
    root = Path(root).resolve()
    m = snapshot["meta"]
    rid = f'{m["day"]}_{str(m["jcd"]).zfill(2)}_{int(m["rno"]):02}'
    if str(m["jcd"]).zfill(2) != "23":
        return {"status": "missing", "reason": "Other venues' measurements not acquired"}
    candidates = []
    for p in (root / "original_foot").glob(rid + "*.json"):
        doc = read_json(p)
        if doc.get("race_id") != rid:
            raise ValueError("Measurement race identity mismatch")
        acq = doc.get("acquisition", {})
        if acq.get("status") != "ok":
            continue
        observed = scenario.aware(acq["retrieved_at"])
        if observed <= scenario.aware(at):
            candidates.append((observed, p, doc))
    if not candidates:
        return {"status": "missing", "reason": "No acquired same-race foot record"}
    observed, path, doc = max(candidates, key=lambda x: (x[0], str(x[1])))
    acq = doc["acquisition"]
    expected = f'https://www.boatrace-karatsu.jp/sp/index.php?page=yosou-cyokuzen&race={int(m["rno"])}'
    if acq.get("url") != expected:
        raise ValueError("Unexpected official measurement source")
    raw_path = (root / acq["raw_path"]).resolve()
    if not raw_path.is_relative_to(root):
        raise ValueError("Measurement raw path escapes source root")
    raw_bytes = raw_path.read_bytes()
    if raw_path.suffix == ".b64":
        raw_bytes = base64.b64decode(raw_bytes)
    raw_bytes = gzip.decompress(raw_bytes)
    if sha256(raw_bytes).hexdigest() != acq["sha256"]:
        raise ValueError("Measurement raw hash mismatch")
    raw = raw_bytes.decode("utf-8")
    if f'{m["day"][:4]}/{m["day"][4:6]}/{m["day"][6:]}' not in raw:
        raise ValueError("Measurement source date mismatch")
    from research.capture_v1.parsers import textify
    text = "".join(textify(raw).split())
    rows = karatsu_foot(raw)
    if {r["lane"] for r in rows} != set(range(1, 7)):
        raise ValueError("Six measurement rows required")
    old = {int(b["lane"]): b for b in snapshot["boats"]}
    for row in rows:
        b = old[row["lane"]]
        if "".join(str(b["name"]).split()) not in text:
            raise ValueError("Measurement roster name mismatch")
        if row.get("exhibition_time") is None or b.get("exhibition_time") is None:
            raise ValueError("Need exhibition-time identity check")
        if abs(row["exhibition_time"] - b["exhibition_time"]) > .011:
            raise ValueError("Measurement exhibition identity mismatch")
        for key in ("straight_time", "turn_time", "lap_time"):
            row[key] = scenario.number(row.get(key), .001, 100)
    deadline = scenario.aware(f'{m["day"][:4]}-{m["day"][4:6]}-{m["day"][6:]}T{m["deadline"]}:00+09:00')
    before = observed < deadline
    if mode == "live" and not before:
        return {"status": "excluded", "reason": "Foot record received after deadline",
                "observed_at": observed.isoformat(), "sha256": acq["sha256"]}
    return {"status": "joined", "rows": rows, "source_url": acq["url"],
            "sha256": acq["sha256"], "observed_at": observed.isoformat(),
            "available_before_deadline": before,
            "measurement_diagram_url": doc.get("measurement_diagram_url"),
            "model_use": "raw times to scenario conditions and followers; no invented motor grade"}


def _scenario(boats, ranking):
    """Reuse v2 tactical functions after this adapter's own time/identity audit.

    Replays can use measurements acquired later and are labelled as such; we
    do not forge a predeadline snapshot timestamp for those measurements.
    """
    projected = deepcopy(boats)
    for b in projected:
        b["course"] = int(b.get("predicted_course") or b["lane"])
    scenario.reject_outcomes(projected)
    by_course = {b["course"]: b for b in projected}
    branches, lanes = [], []
    for b in sorted(projected, key=lambda x: x["lane"]):
        hs = []
        for tactic in (("逃げ",) if b["course"] == 1 else ("差し", "まくり", "まくり差し")):
            origins = [x for x in projected if 1 < x["course"] < b["course"]] if tactic == "まくり差し" else [None]
            for origin in origins:
                hs.append(scenario.build_branch(b, tactic, origin, list(by_course.values())))
        branches.extend(hs)
        lanes.append({"lane": b["lane"], "racer_id": b["racer_id"], "name": b.get("name"),
                      "predicted_course": b["course"], "hypotheses": hs})
    source = {"baseline_ranking": [r["combination"] for r in ranking],
              "baseline_picks": [r["combination"] for r in ranking[:10]]}
    return {"lanes": lanes, "virtual_card": scenario.select_card(source, branches)}


def build(snapshot, materials, *, state_root=None, mode="replay", now=None):
    at = now or clock()
    _, validated_meta, _ = scenario.validate(snapshot, mode, at)
    if mode == "live" and scenario.aware(materials.loaded_at) > scenario.aware(at):
        raise ValueError("Materials were loaded after generation")
    if mode == "live" and materials.latest_history_observed_at and materials.latest_history_observed_at > scenario.aware(at):
        raise ValueError("Historical source observed after generation")
    official = from_frozen_official(snapshot)
    payload = official["payload"]
    control, historical = deepcopy(payload), deepcopy(payload)
    m = snapshot["meta"]
    profiles, applied, motor_context = {}, {}, {}
    for b, prior_b in zip(historical["boats"], control["boats"]):
        lane = int(b["lane"])
        profile = materials.profile(b["racer_id"], b["predicted_course"], m["day"])
        profiles[lane] = profile
        _apply_profile(prior_b, profile, prior_control=True)
        applied[lane] = _apply_profile(b, profile)
        motor_context[lane] = materials.motor_context(m["jcd"], b["motor_number"], m["day"])
    rankings = {name: hybrid._ordered_cards(analyze_race(p)["trifecta"])
                for name, p in (("official_core", payload),
                                ("course_prior_control", control),
                                ("acquired_course_profiles", historical))}
    no_foot = _scenario(historical["boats"], rankings["acquired_course_profiles"])
    foot = load_foot(state_root, snapshot, mode=mode, at=at) if state_root else {
        "status": "missing", "reason": "No separate measurement store supplied"}
    measured_boats = deepcopy(historical["boats"])
    if foot["status"] == "joined":
        by_lane = {r["lane"]: r for r in foot["rows"]}
        for b in measured_boats:
            for key in ("straight_time", "turn_time", "lap_time"):
                b[key] = by_lane[b["lane"]][key]
    final = _scenario(measured_boats, rankings["acquired_course_profiles"])
    cards = {name: [r["combination"] for r in rows[:10]] for name, rows in rankings.items()}
    cards["profiles_plus_yuuki_without_foot"] = no_foot["virtual_card"]["picks"]
    cards["profiles_plus_yuuki_with_measured_foot"] = final["virtual_card"]["picks"]
    for card in cards.values():
        if len(card) != 10 or len(set(card)) != 10 or not set(card) <= scenario.COMBINATIONS:
            raise ValueError("Invalid matched ten-point comparison")
    all_six = []
    for lane in final["lanes"]:
        number = lane["lane"]
        b = next(x for x in measured_boats if x["lane"] == number)
        profile = profiles[number]
        measured = {key: {"seconds": b.get(key), "same_race_rank": scenario.rank_measure(measured_boats, key, number)}
                    for key in ("straight_time", "turn_time", "lap_time")}
        start_rank = scenario.rank_measure(measured_boats, "avg_st", number)
        facts = [f'平均ST {b.get("avg_st")}（6艇内順位 {start_rank}）',
                 f'コース別履歴 {profile["denominator"]}走、1着{profile["wins"]}・2連対{profile["top2_count"]}・3連対{profile["top3_count"]}']
        for key, label in (("straight_time", "直線"), ("turn_time", "回り足"), ("lap_time", "一周")):
            if measured[key]["seconds"] is not None:
                facts.append(f'{label} {measured[key]["seconds"]}秒（同一レース順位 {measured[key]["same_race_rank"]}）')
        supported = [h for h in lane["hypotheses"] if h['supported_observations'] > 0]
        best = sorted(supported, key=lambda h: (-h["supported_observations"], h["id"]))[0] if supported else None
        all_six.append({**lane, "facts": facts, "course_history": profile,
                        "history_fields_applied": applied[number], "measured_foot": measured,
                        "motor_history": motor_context[number],
                        "sample_note": "四場履歴の小標本。全国通算や確定的な得意とは扱わない" if profile["denominator"] < 30 else "四場限定の記述統計",
                        "strongest_observed_hypothesis": best["id"] if best else None,
                        "win_path": best["win_path"] if best else "観測で優先できる勝ち筋なし。全分岐は仮説として保存",
                        "loss_path": best["loss_path"] if best else "各分岐の不成立条件を確認。現時点で攻め方を優先しない",
                        "linked_followers": best["reactions"] if best else []})
    primary = "profiles_plus_yuuki_with_measured_foot"
    changes = {}
    for before, after in (("official_core", "course_prior_control"),
                          ("course_prior_control", "acquired_course_profiles"),
                          ("profiles_plus_yuuki_without_foot", primary)):
        changes[before + " -> " + after] = {
            "added": [x for x in cards[after] if x not in cards[before]],
            "removed": [x for x in cards[before] if x not in cards[after]]}
    output = {"version": VERSION, "research_only": True, "race_id": f'{m["day"]}_{str(m["jcd"]).zfill(2)}_{int(m["rno"]):02}',
              "status": "retrospective_materials_application" if mode == "replay" else "live_uncheckpointed",
              "assembled_at": at, "official_snapshot_captured_at": m["captured_at"],
              "deadline_at": validated_meta['deadline_at'],
              "source_input_digest": scenario.digest(snapshot), "materials_loaded_at": materials.loaded_at,
              "material_sources": materials.sources, "environment": deepcopy(snapshot.get("environment", {})),
              "foot_provenance": {k: v for k, v in foot.items() if k != "rows"},
              "model_cards": cards, "primary_card": primary, "card_changes": changes,
              "all_six": all_six, "ticket_count": 10, "per_ticket_stake_yen": 100,
              "result_accessed": False, "count_as_prospective": False,
              "remote_receipt_confirmed": False, "production_main_parity": False,
              "probabilities_calibrated": False, "expected_value_computed": False,
              "data_use": {"racer_profiles": "main ranking and scenario followers",
                           "measured_foot": "tactic support and second/third formations",
                           "motor_history": "period-separated explanatory context; continuity not yet verified",
                           "weather": "unchanged official-core input and observed race context",
                           "comments_and_tide": "not scored by this first adapter"},
              "limitations": ["Replay is generated now, not an original predeadline forecast",
                              "Four-venue history is not nationwide career performance",
                              "Prior-only and no-foot controls isolate what actual data changed",
                              "Same-race foot timing ranks do not prove actual attacks or calibrated probabilities",
                              "Current motor period, comments and tide need separate source matching before scoring",
                              "Live records need an independently confirmed predeadline remote receipt"]}
    output["digest"] = scenario.digest(output)
    return output


def markdown(record):
    lines = [f'# 研究材料を使った6艇検討：{record["race_id"]}', '',
             f'生成区分：{record["status"]}。生成時刻：{record["assembled_at"]}。',
             '現在の研究処理で再構成した資料。締切前予想の実績には含めない。', '',
             '| 艇 | 選手 | 履歴の母数 | 直線順位 | 回り足順位 | 主な勝ち筋 | 主な負け筋 |',
             '|---|---|---:|---:|---:|---|---|']
    for b in record['all_six']:
        lines.append(f'| {b["lane"]} | {b["name"]} | {b["course_history"]["denominator"]} | '
                     f'{b["measured_foot"]["straight_time"]["same_race_rank"]} | '
                     f'{b["measured_foot"]["turn_time"]["same_race_rank"]} | {b["win_path"]} | {b["loss_path"]} |')
    lines.extend(['', '## 各10点の比較', ''])
    for name, card in record['model_cards'].items():
        lines.extend([f'**{name}**', '', ' / '.join(card), ''])
    lines.extend(['## データが変えた買い目', '', json.dumps(record['card_changes'], ensure_ascii=False, indent=2), '',
                  '全6艇の全分岐・攻め起点・後続反応・条件の根拠は同名JSONに保存。',
                  'モーター履歴は周期を分けて表示し、同じ公式モーター成績を二重加点しない。', ''])
    return '\n'.join(lines)
