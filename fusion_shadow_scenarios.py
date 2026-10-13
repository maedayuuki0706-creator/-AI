"""Prospective six-boat hypotheses from captured values; never a delivery module.

Small bounded research modifiers are explicitly uncalibrated. Missing evidence
stays missing, and a hypothesis is never presented as an observed cause.
"""
from __future__ import annotations

from math import exp, isfinite
from statistics import mean

VERSION = "new-yuuki-six-boat-v2"
METHODS = {1: ["逃げ"], 2: ["差し", "まくり"],
           3: ["まくり", "まくり差し"], 4: ["まくり", "まくり差し", "差し"],
           5: ["まくり差し", "差し", "まくり"], 6: ["まくり差し", "差し", "まくり"]}


def number(value, lo=None, hi=None):
    try:
        value = float(value)
        if not isfinite(value) or lo is not None and value < lo or hi is not None and value > hi:
            return None
        return value
    except (TypeError, ValueError):
        return None


def _clip(value, low, high):
    return max(low, min(high, value))


def _text(value):
    return "未取得" if value is None else str(value)


def build(analyses, baseline_rows, context=None):
    official = analyses["existing"]
    boats = {int(b["lane"]): b for b in official["inputs"]}
    courses = {lane: int(b.get("predicted_course") or b.get("course") or lane)
               for lane, b in boats.items()}
    if set(courses.values()) != set(range(1, 7)):
        raise ValueError("Six observed unique exhibition courses are required")
    course_lanes = {course: lane for lane, course in courses.items()}
    hiyori = {int(f["lane"]): f for f in analyses["hiyori"].get("features", []) if f.get("lane")}
    db = analyses["sheet_db"]["sheet_database"]
    db_detail = db.get("lane_factors") or {}
    db_boats = ({int(l): f for l, f in db_detail.items()} if isinstance(db_detail, dict)
                else {int(f["lane"]): f for f in db_detail if f.get("lane")})
    head_prior = {lane: sum(r["probability"] for r in baseline_rows
                           if r["combination"].startswith(f"{lane}-")) for lane in boats}
    motors = [number(boats[l].get("motor_top2_rate"), 0, 100) for l in range(1, 7)]
    motor_center = mean(v for v in motors if v is not None) if any(v is not None for v in motors) else None
    ability = [number(boats[l].get("win_rate"), 0, 10) for l in range(1, 7)]
    ability_center = mean(v for v in ability if v is not None) if any(v is not None for v in ability) else None
    rows, factors = [], {}
    for lane, b in sorted(boats.items()):
        course = courses[lane]
        inside_lane, outside_lane = course_lanes.get(course-1), course_lanes.get(course+1)
        inside = boats.get(inside_lane, {})
        outside = boats.get(outside_lane, {})
        avg = number(b.get("avg_st"), .01, .6)
        ins_avg, out_avg = number(inside.get("avg_st"), .01, .6), number(outside.get("avg_st"), .01, .6)
        exhibition = number(b.get("exhibition_st"), 0, .99)
        exhibition_signed = number(b.get("exhibition_st_timing"), -.99, .99)
        ins_ex = number(inside.get("exhibition_st"), 0, .99)
        out_ex = number(outside.get("exhibition_st"), 0, .99)
        motor, win_rate = motors[lane-1], ability[lane-1]
        evidence = {
            "average_st": avg, "exhibition_st": exhibition,
            "exhibition_st_signed": exhibition_signed,
            "exhibition_time": number(b.get("exhibition_time"), 5, 9),
            "exhibition_rank": b.get("exhibition_rank"),
            "motor_top2_rate": motor, "motor_number": b.get("motor_number"),
            "national_win_rate": win_rate, "current_class": b.get("current_class"),
            "tilt": number(b.get("tilt"), -1, 4),
            "hiyori_course_samples": hiyori.get(lane, {}).get("course_samples"),
            "hiyori_course_win_rate": hiyori.get(lane, {}).get("course_win_rate"),
            "hiyori_used": hiyori.get(lane, {}).get("used", []),
            "db_adjustment": db_boats.get(lane),
            "db_snapshot_at": db.get("snapshot_at"),
            "previous_day_form": (official.get("previous_form") or {}).get(lane),
        }
        missing = [name for name in ("average_st", "exhibition_st", "exhibition_time",
                                     "motor_top2_rate", "national_win_rate", "tilt") if evidence[name] is None]
        if not evidence["previous_day_form"]:
            missing.append("previous_day_form")
        if not evidence["db_adjustment"]:
            missing.append("db_individual_adjustment")
        note = [f"想定{course}コース。展示進入は本番を保証しない",
                f"平均ST={_text(avg)}、展示ST={_text(exhibition)}、モーター2連率={_text(motor)}%",
                f"全国勝率={_text(win_rate)}、級別={_text(b.get('current_class'))}"]
        if exhibition_signed is not None and exhibition_signed < 0:
            note.append(f"展示F={abs(exhibition_signed):.2f}。本番STに置換せずST加点は無効")
            exhibition = None
        score, components = 0., []
        tests = []
        wins, losses, conditions = [], [], []
        if course == 1:
            wins.append("1コースから先マイし、差し場を小さく保って逃げる")
            conditions.append("外の攻撃より先に旋回位置を確保し、出口で流れない")
            losses.append("2コースの差し／外艇のまくりで先マイの優位を失う")
        elif course == 2:
            wins.append(f"1コース{course_lanes[1]}号艇の旋回後に差し場を確保する")
            conditions.append("インの出口に差し場が生じ、外の攻撃より先に内側を取る")
            losses.append("インの旋回が小さく差し場がなく、外艇の攻撃に先を越される")
        elif course in (3, 4):
            wins.append(f"内隣{inside_lane}号艇の壁を越えてまくる／開いた間をまくり差す")
            conditions.append("スタートと行き足の差が本番でも成立し、攻めの進路を確保する")
            losses.append(f"内隣{inside_lane}号艇が壁となるか、外艇に進路を取られる")
        else:
            wins.append("内側の攻めと競りに乗り、まくり差し／差しで空いた進路を取る")
            conditions.append("内の競りによる進路と、自艇が追いつける行き足が同時に必要")
            losses.append("内側が競らず先行するか、外回りの距離ロスで攻めが届かない")
        if avg is not None and ins_avg is not None:
            gap = ins_avg-avg
            delta = .10 * _clip(gap/.05, -1, 1)
            score += delta
            components.append({"field": "historical_st_vs_inside", "observed_gap": gap, "log_factor": delta})
            note.append(f"内隣{inside_lane}号艇との平均ST差={gap:+.3f}秒（正なら自艇が早い）")
            tests.append({"kind": "st_advantage", "other_lane": inside_lane, "threshold": .03})
            if gap >= .03:
                conditions.append(f"平均STの内隣に対する優位{gap:.3f}秒が本番でも再現する")
            losses.append("平均STの優位は過去平均であり、本番で再現しない可能性がある")
        if exhibition is not None and ins_ex is not None:
            gap = ins_ex-exhibition
            delta = .035 * _clip(gap/.08, -1, 1)
            score += delta
            components.append({"field": "exhibition_st_vs_inside", "observed_gap": gap, "log_factor": delta})
            note.append(f"展示で内隣{inside_lane}号艇とのST差={gap:+.3f}秒（展示のみ）")
            losses.append("展示ST差が本番で消えると、この攻めの根拠は崩れる")
        if avg is not None and out_avg is not None:
            gap = avg-out_avg
            delta = -.055 * _clip(gap/.05, -1, 1)
            score += delta
            components.append({"field": "historical_st_vs_outside", "observed_gap": gap, "log_factor": delta})
            if gap >= .03:
                losses.append(f"外隣{outside_lane}号艇の平均STが{gap:.3f}秒早く、攻撃を受ける条件")
                tests.append({"kind": "outside_attack", "other_lane": outside_lane, "threshold": .03})
        if motor is not None and motor_center is not None:
            delta = .035 * _clip((motor-motor_center)/20, -1, 1)
            score += delta
            components.append({"field": "motor_top2_vs_race_mean", "observed_gap": motor-motor_center, "log_factor": delta})
            note.append(f"モーター2連率の6艇中の取得値平均との差={motor-motor_center:+.1f}pt。現在の足を保証しない")
        if win_rate is not None and ability_center is not None:
            delta = .035 * _clip((win_rate-ability_center)/2, -1, 1)
            score += delta
            components.append({"field": "national_win_rate_vs_race_mean", "observed_gap": win_rate-ability_center, "log_factor": delta})
        factor = exp(_clip(score, -.25, .25))
        factors[lane] = factor
        rows.append({"lane": lane, "racer_id": str(b["racer_id"]), "name": b.get("name"),
                     "predicted_course": course, "inside_lane": inside_lane, "outside_lane": outside_lane,
                     "head_probability_before_scenarios": head_prior[lane],
                     "scenario_factor": factor, "factor_components": components,
                     "win_paths": wins, "win_conditions": conditions, "loss_paths": losses,
                     "anticipated_methods": METHODS[course], "condition_tests": tests,
                     "evidence": evidence, "evidence_notes": note, "missing_fields": missing,
                     "inference_type": "pre_race_unvalidated_hypothesis", "excluded_accidents": True})
    return rows, factors


def rank(analyses, baseline_rows, context=None):
    scenarios, factors = build(analyses, baseline_rows, context)
    total = sum(r["probability"]*factors[int(r["combination"][0])] for r in baseline_rows)
    rows = []
    for original in baseline_rows:
        row = dict(original)
        lane = int(row["combination"][0])
        factor = factors[lane]/total
        row.update(probability=row["probability"]*factor,
                   rank_score=row["rank_score"]*factor, cover_score=row["cover_score"]*factor,
                   expected_value=row["probability"]*factor*row["odds"] if row["odds"] is not None else None)
        rows.append(row)
    rows.sort(key=lambda r: (-r["rank_score"], r["combination"]))
    main = [r["combination"] for r in rows[:6]]
    heads = {lane: sum(r["probability"] for r in rows if r["combination"].startswith(f"{lane}-")) for lane in range(1, 7)}
    # Reserve cover for supported alternate heads, then use the frozen EV score.
    cover_ranked = sorted((r for r in rows if r["combination"] not in main),
                          key=lambda r: (-r["cover_score"], r["combination"]))
    main_heads = {int(c[0]) for c in main}
    supported = {s["lane"] for s in scenarios if heads[s["lane"]] >= .05
                 and any(c["log_factor"] > 0 for c in s["factor_components"])}
    cover = []
    covered_heads = set(main_heads)
    for row in cover_ranked:
        lane = int(row["combination"][0])
        if lane in supported and lane not in covered_heads and len(cover) < 4:
            cover.append(row["combination"])
            covered_heads.add(lane)
    for row in cover_ranked:
        if len(cover) >= 4:
            break
        if row["combination"] not in cover:
            cover.append(row["combination"])
    chosen = set(main+cover)
    for s in scenarios:
        lane = s["lane"]
        s["head_probability"] = heads[lane]
        s["head_tickets"] = [c for c in main+cover if int(c[0]) == lane]
        s["axis_decision"] = "頭採用" if s["head_tickets"] else "頭不採用"
        s["axis_reason"] = (f"補正後の頭確率{heads[lane]:.1%}。" +
                            ("確率順位／代替頭の根拠で10点に採用" if s["head_tickets"] else
                             "勝つ筋は検討したが、確率順位と根拠を比較した10点の採用枠外。勝てないという判断ではない"))
    reasons = {}
    indexed = {s["lane"]: s for s in scenarios}
    for row in rows:
        combo = row["combination"]
        if combo not in chosen:
            continue
        first, second, third = map(int, combo.split("-"))
        joint_two = sum(r["probability"] for r in rows if r["combination"].startswith(f"{first}-{second}-"))
        reasons[combo] = {"bucket": "main" if combo in main else "cover",
                          "probability": row["probability"], "odds": row["odds"],
                          "expected_value": row["expected_value"],
                          "second_given_head": joint_two/heads[first] if heads[first] else None,
                          "third_given_head_second": row["probability"]/joint_two if joint_two else None,
                          "support_families": row["support_families"],
                          "head_win_path": indexed[first]["win_paths"],
                          "conditions": indexed[first]["win_conditions"],
                          "finishers_evidence": {str(l): indexed[l]["evidence"] for l in (first, second, third)},
                          "note": "頭条件付きの2・3着確率は融合120通りから算出。確率・研究係数は未校正"}
    return rows, main, cover, scenarios, reasons


def evaluate_hypotheses(record, result):
    details = result.get("race_details") or {}
    actual = {int(b["lane"]): b for b in details.get("finish", []) if b.get("lane")}
    winners = sorted({int(c[0]) for c in result.get("payouts", {})})
    known_abnormal = any(b.get("status") not in (None, "finished") for b in actual.values()) or details.get("method") == "恵まれ"
    complete_status = len(actual) == 6 and all(b.get("status") is not None for b in actual.values())
    abnormal = True if known_abnormal else False if complete_status else None
    expected_courses = {s["lane"]: s["predicted_course"] for s in record.get("boat_scenarios", [])}
    rows = []
    for s in record.get("boat_scenarios", []):
        lane = s["lane"]
        b = actual.get(lane, {})
        st = number(b.get("st"), 0, 1)
        checked = []
        for condition in s["condition_tests"]:
            other_boat = actual.get(condition["other_lane"], {})
            other = number(other_boat.get("st"), 0, 1)
            met = None
            entry_matches = (b.get("course") == s["predicted_course"] and
                             other_boat.get("course") == expected_courses.get(condition["other_lane"]))
            if not abnormal and entry_matches and st is not None and other is not None:
                gap = other-st if condition["kind"] == "st_advantage" else st-other
                met = gap >= condition["threshold"]
            checked.append({**condition, "observed": met})
        method = details.get("method")
        won = lane in winners
        expected_method = method in s["anticipated_methods"] if won and method and not abnormal else None
        loss_checks = [t for t in checked if t["kind"] == "outside_attack" and t["observed"] is not None]
        anticipated_loss = any(t["observed"] for t in loss_checks) if not won and loss_checks and not abnormal else None
        rows.append({"lane": lane, "won": won, "actual_st": st, "actual_course": b.get("course"),
                     "method_matches_win_hypothesis": expected_method,
                     "pre_loss_condition_observed": anticipated_loss, "condition_checks": checked,
                     "entry_matches_hypothesis": b.get("course") == s["predicted_course"] if b.get("course") is not None else None,
                     "causal_attribution": "abnormal_race_excluded" if abnormal else "unverified_without_race_video",
                     "missing_post_race_fields": [k for k,v in (("actual_st",st),("actual_course",b.get("course")),("winning_method",method)) if v is None]})
    chosen = set(record["models"]["fusion"]["picks"])
    hit = bool(chosen.intersection(result.get("payouts", {})))
    misses = []
    for winner in result.get("payouts", {}):
        if winner not in chosen:
            first = int(winner[0])
            s = next((x for x in record.get("boat_scenarios", []) if x["lane"] == first), {})
            misses.append({"combination": winner, "winning_head_was_considered": bool(s),
                           "winning_head_selected": bool(s.get("head_tickets")),
                           "pre_race_missing_fields": s.get("missing_fields", []),
                           "reason": "頭不採用" if not s.get("head_tickets") else "頭採用済み・2/3着の選択外"})
    return {"boats": rows, "hit": hit, "miss_reasons": misses,
            "abnormal_race_detected": abnormal,
            "ordinary_scenario_learning_eligible": abnormal is False and details.get("method") is not None,
            "next_hypotheses": ["平均ST差と展示ST差の本番再現性を、同じ進入・場条件で比較する",
                                "頭を採用した外れと、頭を採用しなかった外れを分けて検証する"],
            "note": "公式着順・ST・決まり手との整合確認。映像なしで勝敗の原因を断定しない"}
