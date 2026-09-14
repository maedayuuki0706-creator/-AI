"""Independent 100-point score for selected Boat AI Navi races.

The existing A/B/C grade is intentionally unchanged. It describes the shape of
the likely winner. This module separately scores how attractive the race is as
a betting candidate, then uses 75+ for selected and 85+ for strong selected.
"""


def _scale(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _inverse_scale(value, best, worst):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if worst <= best:
        return 0.0
    return max(0.0, min(1.0, (worst - value) / (worst - best)))


def _position_gap(analysis, position):
    totals = {lane: 0.0 for lane in range(1, 7)}
    for row in analysis.get("trifecta", []):
        try:
            lane = int(row["combination"].split("-")[position])
            totals[lane] += float(row.get("probability") or 0.0)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    ranked = sorted(totals.values(), reverse=True)
    return ranked[0] - ranked[1] if len(ranked) >= 2 else 1.0


def race_score(analysis, allocation):
    """Return total 0-100 and a transparent component breakdown.

    Weights:
      head trust 25
      2nd/3rd readability 15
      exhibition/ST 15
      racer/course 15
      motor 10
      odds/EV 15
      conditions 5
    """
    heads = analysis.get("heads") or {}
    ranked_heads = sorted(heads.items(), key=lambda item: float(item[1]), reverse=True)
    if not ranked_heads:
        return 0, {}

    leader_lane = int(ranked_heads[0][0])
    top = float(ranked_heads[0][1])
    second = float(ranked_heads[1][1]) if len(ranked_heads) > 1 else 0.0
    gap = max(0.0, top - second)

    head = 12.0 + 7.0 * _scale(top, 0.25, 0.50) + 6.0 * _scale(gap, 0.05, 0.22)
    head = min(25.0, head)

    second_gap = _position_gap(analysis, 1)
    third_gap = _position_gap(analysis, 2)
    support = 5.0 + 5.0 * _scale(second_gap, 0.02, 0.12) + 5.0 * _scale(third_gap, 0.02, 0.10)
    support = min(15.0, support)

    boats = {
        int(boat.get("lane")): boat
        for boat in (analysis.get("inputs") or [])
        if boat.get("lane") is not None
    }
    leader = boats.get(leader_lane, {})
    preview = analysis.get("preview") or {}

    exhibition_count = int(preview.get("exhibition_count") or 0)
    if exhibition_count >= 6:
        ex_grade = float(leader.get("exhibition_grade") or 0.0)
        st = leader.get("exhibition_st")
        if st is None:
            st = leader.get("avg_st")
        exhibition_st = 6.0 + 5.0 * max(0.0, min(1.0, ex_grade))
        exhibition_st += 4.0 * _inverse_scale(st, 0.10, 0.24)
    else:
        exhibition_st = 6.0 * max(0.0, min(1.0, exhibition_count / 6.0))
    exhibition_st = min(15.0, exhibition_st)

    racer_course = 7.0 * _scale(leader.get("win_rate"), 4.0, 7.5)
    racer_course += 4.0 * _scale(leader.get("top2_rate"), 25.0, 55.0)
    course = int(leader.get("predicted_course") or leader.get("course") or leader_lane)
    racer_course += {1: 4.0, 2: 3.4, 3: 3.0, 4: 2.6, 5: 2.2, 6: 1.8}.get(course, 0.0)
    racer_course = min(15.0, racer_course)

    motor = 7.0 * _scale(leader.get("motor_top2_rate"), 20.0, 55.0)
    motor += 3.0 * _scale(leader.get("motor_top3_rate"), 30.0, 70.0)
    motor = min(10.0, motor)

    bets = list((allocation or {}).get("bets") or [])
    if (allocation or {}).get("status") == "bet" and bets:
        best_ev = max(float(bet.get("expected_value") or 0.0) for bet in bets)
        ev = 5.0 + 10.0 * _scale(best_ev, 1.05, 2.00)
    else:
        ev = 0.0
    ev = min(15.0, ev)

    wind = preview.get("wind_speed")
    wave = preview.get("wave_cm")
    if wind is None or wave is None:
        conditions = 2.5
    else:
        conditions = 3.0 * _inverse_scale(wind, 2.0, 6.0)
        conditions += 2.0 * _inverse_scale(wave, 2.0, 8.0)
    conditions = min(5.0, conditions)

    breakdown = {
        "head": round(head, 1),
        "support": round(support, 1),
        "exhibition_st": round(exhibition_st, 1),
        "racer_course": round(racer_course, 1),
        "motor": round(motor, 1),
        "ev": round(ev, 1),
        "conditions": round(conditions, 1),
    }
    total = int(round(sum(breakdown.values())))
    return max(0, min(100, total)), breakdown


def badge(score):
    if score >= 85:
        return "🔥🔥強厳選"
    if score >= 75:
        return "🔥厳選"
    return "通常"


def install(app):
    """Install scoring around the existing notifier without changing A/B/C."""
    original_message = app.analysis_message_with_virtual
    original_log = app.log_prediction_with_virtual
    score_cache = {}

    def scored_message(day, jcd, rno, deadline, phase, analysis, rows, required):
        message = original_message(day, jcd, rno, deadline, phase, analysis, rows, required)
        key = (day, str(jcd), int(rno), phase)
        allocation = app._VIRTUAL.get(key) or {}
        score, breakdown = race_score(analysis, allocation)
        score_cache[key] = {"score": score, "breakdown": breakdown}

        if phase == "final" and int((analysis.get("preview") or {}).get("exhibition_count") or 0) >= 6:
            score_line = f"**総合スコア {score}/100｜{badge(score)}**"
            marker = "\n\n**仮想投票"
            if marker in message:
                candidate = message.replace(marker, "\n\n" + score_line + marker, 1)
            else:
                candidate = message + "\n\n" + score_line
            if len(candidate.encode("utf-16-le")) // 2 <= 2000:
                message = candidate
        return message

    def is_selected(record):
        return (
            record.get("phase") == "final"
            and bool(record.get("exhibition"))
            and int(record.get("selection_score") or 0) >= 75
            and record.get("virtual_status") == "bet"
        )

    def selected_message(record):
        score = int(record.get("selection_score") or 0)
        prefix = "🔥🔥 **強厳選予想" if score >= 85 else "🔥 **厳選予想"
        heads = record.get("heads") or {}
        ranked = sorted(heads.items(), key=lambda item: float(item[1]), reverse=True)
        top_text = ""
        if ranked:
            top_text = f"\n頭評価：{ranked[0][0]}号艇 {float(ranked[0][1]) * 100:.1f}%"
            if len(ranked) > 1:
                top_text += f" / 対抗{ranked[1][0]}号艇 {float(ranked[1][1]) * 100:.1f}%"

        selected_bets = [
            bet for bet in (record.get("virtual_bets") or [])
            if float(bet.get("expected_value") or 0) >= 1.15
            and float(bet.get("probability") or 0) >= 0.015
        ]
        ev_text = " / ".join(
            f"{bet['combination']} {float(bet.get('odds') or 0):.1f}倍 EV{float(bet.get('expected_value') or 0):.2f}"
            for bet in selected_bets[:3]
        ) or "仮想投票条件クリア"

        main = " / ".join(record.get("main") or []) or "-"
        cover = " / ".join((record.get("cover") or [])[:6]) or "-"
        bd = record.get("selection_score_breakdown") or {}
        breakdown_text = (
            f"頭{bd.get('head', 0)}/25・相手{bd.get('support', 0)}/15・展示/ST{bd.get('exhibition_st', 0)}/15・"
            f"選手/コース{bd.get('racer_course', 0)}/15・モーター{bd.get('motor', 0)}/10・"
            f"EV{bd.get('ev', 0)}/15・条件{bd.get('conditions', 0)}/5"
        )
        return (
            f"{prefix}｜{record.get('venue')} {record.get('rno')}R**\n"
            f"締切 **{record.get('deadline')}** / 評価 **{record.get('grade')}** / 総合スコア **{score}/100**"
            f"{top_text}\n"
            f"◎ 本線：{main}\n"
            f"○ 押さえ：{cover}\n"
            f"スコア内訳：{breakdown_text}\n"
            f"選定理由：総合75点以上＋展示確定＋仮想投票条件クリア\n"
            f"EV候補：{ev_text}"
        )

    def scored_log(record):
        key = (
            record.get("day"),
            str(record.get("jcd")),
            int(record.get("rno", 0)),
            record.get("phase", "final"),
        )
        info = score_cache.get(key)
        if info is not None:
            record = dict(record)
            record["selection_score"] = info["score"]
            record["selection_score_breakdown"] = info["breakdown"]
            record["selection_score_version"] = "selected-score-v1"
            record["selection_threshold"] = 75
            record["strong_selection_threshold"] = 85
        return original_log(record)

    app.analysis_message_with_virtual = scored_message
    app.log_prediction_with_virtual = scored_log
    app._is_selected_record = is_selected
    app._selected_message = selected_message
