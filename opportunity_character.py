"""Character voice and compact display metrics for 中穴 / 穴 opportunity channels.

Selection, scoring and ticket construction stay untouched. User-facing cards show
only three evaluation metrics: 合成倍率, 荒れ期待度, and 狙い指数. The selected
中穴 stream keeps the separate 厳選くん voice.
"""
from __future__ import annotations

import random


_METRIC_CACHE = {}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clip(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _scale(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if high <= low:
        return 0.0
    return _clip((value - low) / (high - low))


def _market_is_split(analysis) -> bool:
    """Conservatively call the market split only when the shortest odds cluster."""
    odds = sorted(
        _num(row.get("odds"))
        for row in (analysis.get("trifecta") or [])
        if _num(row.get("odds")) > 0
    )
    if len(odds) < 3:
        return False
    favorite = odds[0]
    if favorite <= 0:
        return False
    return odds[1] <= favorite * 1.30 and odds[2] <= favorite * 1.75


def _best_ev(picks) -> float:
    best = 0.0
    for row in picks or []:
        ev = row.get("expected_value")
        if ev is None:
            ev = _num(row.get("odds")) * _num(row.get("probability"))
        best = max(best, _num(ev))
    return best


def _best_odds(picks) -> float:
    return max((_num(row.get("odds")) for row in (picks or [])), default=0.0)


def _composite_odds(picks):
    """Return equal-payout composite odds for the displayed ticket set.

    With no stake weights on the opportunity feed, 1/sum(1/odds) is the neutral
    way to summarize the whole set without pretending every ticket has one common
    hit probability. If stake weights are added later, this can be replaced with
    the actual weighted payout multiple.
    """
    odds = [_num(row.get("odds")) for row in (picks or [])]
    odds = [value for value in odds if value > 0]
    if not odds:
        return None
    inverse = sum(1.0 / value for value in odds)
    if inverse <= 0:
        return None
    return round(1.0 / inverse, 1)


def _upset_expectation(analysis):
    """Score race-level volatility from conditions and entry structure only.

    This is deliberately separate from the opportunity score. It does not use
    selected-ticket odds or EV, so a high value means 'the race itself has more
    upset ingredients', not 'this bet is likely to hit'.
    """
    preview = analysis.get("preview") or {}
    inputs = list(analysis.get("inputs") or [])
    heads = analysis.get("heads") or {}
    head_values = sorted((_num(value) for value in heads.values()), reverse=True)
    top_head = head_values[0] if head_values else 0.35
    one_head = _num(heads.get("1"), 0.35)

    # Unclear winner / vulnerable inside: 40 points total.
    head_uncertainty = 20.0 * (1.0 - _scale(top_head, 0.22, 0.48))
    inside_vulnerability = 20.0 * (1.0 - _scale(one_head, 0.14, 0.36))

    # Weather / water: up to 35 points.
    wind = preview.get("wind_speed")
    wave = preview.get("wave_cm")
    wind_speed = 15.0 * _scale(wind, 2.0, 7.0)
    wave_score = 10.0 * _scale(wave, 2.0, 10.0)

    wind_dir = str(preview.get("wind_direction") or "").lower()
    direction = 0.0
    if any(word in wind_dir for word in ("向かい", "head")):
        direction = 5.0
    elif any(word in wind_dir for word in ("横", "cross")):
        direction = 4.0
    elif any(word in wind_dir for word in ("追い", "tail")) and _num(wind) >= 4.0:
        direction = 2.0

    weather = str(preview.get("weather") or "").lower()
    weather_score = 5.0 if any(word in weather for word in ("雨", "雪", "雷", "rain", "snow", "storm")) else 0.0

    # Entry changes / front-taking / deep inside: up to 15 points.
    changed = 0
    front_or_deep = False
    exhibition_st = []
    for boat in inputs:
        try:
            lane = int(boat.get("lane"))
            course = int(boat.get("predicted_course") or boat.get("course") or lane)
        except (TypeError, ValueError):
            lane = course = 0
        if lane and course and lane != course:
            changed += 1
        if boat.get("front_entry") or boat.get("deep_inside"):
            front_or_deep = True
        st = boat.get("exhibition_st")
        try:
            st = float(st)
        except (TypeError, ValueError):
            st = None
        if st is not None and 0 <= st <= 1:
            exhibition_st.append(st)

    entry_change = min(11.0, changed * 3.5)
    entry_special = 4.0 if front_or_deep else 0.0

    # Large exhibition ST dispersion can create attack/late-start asymmetry: 10 points.
    st_spread_score = 0.0
    if len(exhibition_st) >= 4:
        st_spread_score = 10.0 * _scale(max(exhibition_st) - min(exhibition_st), 0.03, 0.12)

    parts = {
        "head_uncertainty": round(head_uncertainty, 1),
        "inside_vulnerability": round(inside_vulnerability, 1),
        "wind_speed": round(wind_speed, 1),
        "wind_direction": round(direction, 1),
        "wave": round(wave_score, 1),
        "weather": round(weather_score, 1),
        "entry_change": round(entry_change, 1),
        "front_or_deep": round(entry_special, 1),
        "st_spread": round(st_spread_score, 1),
    }
    score = int(round(min(100.0, sum(parts.values()))))
    return score, parts


def _upset_level(score):
    """Convert the internal 0-100 volatility score to a user-facing five-level label."""
    score = max(0, min(100, int(round(_num(score)))))
    if score >= 80:
        return "Lv5｜大荒れ警戒"
    if score >= 60:
        return "Lv4｜波乱気配"
    if score >= 40:
        return "Lv3｜混戦気味"
    if score >= 20:
        return "Lv2｜落ち着き気味"
    return "Lv1｜かなり穏やか"


def _replace_metric_display(message, analysis, picks, score):
    composite = _composite_odds(picks)
    upset, _ = _upset_expectation(analysis)
    composite_text = "-" if composite is None else f"{composite:.1f}倍"

    lines = str(message).splitlines()
    out = []
    skipping_payout = False
    inserted = False
    for line in lines:
        if line.startswith("期待度 **"):
            out.extend((
                f"📊 **合成倍率 {composite_text}**",
                f"🌊 **荒れ期待度 {_upset_level(upset)}**",
                f"🎯 **狙い指数 {int(score or 0)}/100**",
            ))
            inserted = True
            continue
        if line.strip() == "**想定配当**":
            skipping_payout = True
            continue
        if skipping_payout:
            if line.strip() == "**根拠**":
                while out and not out[-1].strip():
                    out.pop()
                out.extend(("", line))
                skipping_payout = False
            continue
        out.append(line)

    if not inserted:
        metrics = [
            f"📊 **合成倍率 {composite_text}**",
            f"🌊 **荒れ期待度 {_upset_level(upset)}**",
            f"🎯 **狙い指数 {int(score or 0)}/100**",
        ]
        insert_at = 1 if out else 0
        out[insert_at:insert_at] = metrics
    return "\n".join(out)


def _mid_line(analysis, picks, score) -> str:
    """Easygoing value-hunter: smells out tasty mid-odds without overclaiming."""
    if not picks:
        return random.choice((
            "🟡 「今日はまだ美味しそうな匂いせんなぁ。無理せず待つよ👀」",
            "🟡 「ここはまだ手を出さんでいいかな。もっと美味しいところ待ち🔥」",
        ))

    if _market_is_split(analysis):
        return random.choice((
            "🟡 「オッズ割れてるなぁここ。こういうレース、好きよ🔥」",
            "🟡 「人気バラけてるねぇ。ん〜、美味しそうな匂いするなぁここ👀」",
            "🟡 「みんな迷ってるねぇ。こういう時こそ中穴の出番かな🔥」",
        ))

    if _best_ev(picks) >= 1.35:
        return random.choice((
            "🟡 「ここ、ちょいウマくない？数字もちゃんとついてきてる🔥」",
            "🟡 「ん〜、美味しそうな匂いするなぁここ👀」",
            "🟡 「人気通りだけで終わるかなぁ。ここ、ちょっと美味しそう🔥」",
        ))

    if int(score or 0) >= 75:
        return random.choice((
            "🟡 「ここ、ちょいウマくない？👀」",
            "🟡 「なんか匂うなぁここ。こういう中穴、好きよ🔥」",
            "🟡 「本命だけじゃつまらんでしょ。ここは少し狙いたい🔥」",
        ))

    return random.choice((
        "🟡 「気配はあるねぇ。もう一押し欲しいところ👀」",
        "🟡 「ちょっと匂う。でもまだ飛びつくほどじゃないかな🔥」",
    ))


def _long_line(analysis, picks, score) -> str:
    """Day-job data analyst, off-hours sniper: quiet and data-first."""
    if not picks:
        return random.choice((
            "🔴📊 「解析完了。今回はノイズ判定。トリガーは引かない。」",
            "🔴📊 「有効なターゲットなし。今日は撃たない。」",
        ))

    ev = _best_ev(picks)
    odds = _best_odds(picks)
    if ev >= 1.35 and odds >= 80:
        return random.choice((
            "🔴📊 「……異常値を検知。人気の死角に反応あり。照準、合った。🎯」",
            "🔴📊 「解析完了。オッズの死角にターゲット捕捉。🎯」",
            "🔴📊 「ログ上は小さなズレ。でも俺には十分。照準、合った。🎯」",
        ))

    if int(score or 0) >= 75:
        return random.choice((
            "🔴📊 「人気は薄い。でもデータは残ってる。ターゲット捕捉。🎯」",
            "🔴📊 「この狙い目、まだ目立ってない。照準だけ合わせておく。🎯」",
            "🔴📊 「解析終了。切るには材料が残りすぎてる。🎯」",
        ))

    return random.choice((
        "🔴📊 「候補には残る。だが、まだ撃つ距離じゃない。」",
        "🔴📊 「反応あり。ただし照準は仮固定。もう一段データ待ち。」",
    ))


def _strip_mid_character_prefix(message: str) -> str:
    lines = str(message).splitlines()
    if lines and lines[0].startswith("🟡 「"):
        lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


def install(opportunity_alerts_module):
    """Install character voice and the three-metric display without changing picks."""
    if getattr(opportunity_alerts_module, "_character_voice_installed", False):
        return

    original_message = opportunity_alerts_module._message
    original_selected_mid = opportunity_alerts_module._selected_mid_message
    original_build_payload = opportunity_alerts_module._build_payload
    original_append_log = opportunity_alerts_module._append_log

    def character_message(venue, rno, deadline, analysis, picks, kind, score, breakdown):
        body = original_message(venue, rno, deadline, analysis, picks, kind, score, breakdown)
        body = _replace_metric_display(body, analysis, picks, score)
        if kind == "mid":
            intro = _mid_line(analysis, picks, score)
        else:
            intro = _long_line(analysis, picks, score)
        return f"{intro}\n\n{body}"

    def build_payload(venue, rno, deadline, analysis, kind):
        payload = original_build_payload(venue, rno, deadline, analysis, kind)
        picks = payload.get("picks") or []
        composite = _composite_odds(picks)
        upset, upset_parts = _upset_expectation(analysis)
        payload["composite_odds"] = composite
        payload["upset_expectation"] = upset
        payload["upset_level"] = _upset_level(upset)
        payload["upset_breakdown"] = upset_parts
        stream = "mid_odds" if kind == "mid" else "longshot"
        _METRIC_CACHE[(str(venue), int(rno), stream)] = {
            "composite_odds": composite,
            "upset_expectation": upset,
            "upset_level": _upset_level(upset),
            "upset_breakdown": upset_parts,
            "metric_version": "opportunity-three-metrics-v2",
        }
        return payload

    def append_log(record):
        key = (str(record.get("venue")), int(record.get("rno") or 0), str(record.get("stream") or ""))
        metric = _METRIC_CACHE.pop(key, None)
        if metric:
            record = dict(record)
            record.update(metric)
        return original_append_log(record)

    def selected_mid_message(message):
        # 厳選くん already has its own character. Do not mix the 中穴 voice into it.
        return original_selected_mid(_strip_mid_character_prefix(message))

    opportunity_alerts_module._message = character_message
    opportunity_alerts_module._build_payload = build_payload
    opportunity_alerts_module._append_log = append_log
    opportunity_alerts_module._selected_mid_message = selected_mid_message
    opportunity_alerts_module._character_voice_installed = True
