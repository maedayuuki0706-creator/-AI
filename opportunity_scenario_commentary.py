"""Scenario-first commentary for 中穴AI / 穴AI Discord messages.

The opportunity selector still decides *what* to buy.  This module only changes
*how the reason is explained*: race-flow first, price/EV second.  It uses data
already present in the final official analysis (entry, exhibition ST/time,
motor rates, head probabilities, wind and the selected combinations).
"""
from __future__ import annotations

from collections import Counter


CIRCLED = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥"}


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _lane_text(lane) -> str:
    try:
        lane = int(lane)
    except (TypeError, ValueError):
        return str(lane)
    return CIRCLED.get(lane, str(lane))


def _combo_parts(row):
    combo = str(row.get("combination") or "")
    parts = combo.split("-")
    if len(parts) != 3:
        return None
    try:
        lanes = tuple(int(x) for x in parts)
    except ValueError:
        return None
    return lanes if len(set(lanes)) == 3 else None


def _inputs_by_lane(analysis):
    out = {}
    for row in analysis.get("inputs") or []:
        try:
            out[int(row.get("lane"))] = row
        except (TypeError, ValueError):
            continue
    return out


def _scored_by_lane(analysis):
    out = {}
    for row in analysis.get("boats") or []:
        try:
            out[int(row.get("lane"))] = row
        except (TypeError, ValueError):
            continue
    return out


def _primary_head(picks):
    counts = Counter()
    order = []
    for row in picks:
        parts = _combo_parts(row)
        if not parts:
            continue
        head = parts[0]
        counts[head] += 1
        if head not in order:
            order.append(head)
    if not counts:
        return None
    return max(order, key=lambda lane: counts[lane])


def _support_lanes(picks, head):
    counts = Counter()
    for row in picks:
        parts = _combo_parts(row)
        if not parts or parts[0] != head:
            continue
        # Second place matters a little more than third when describing flow.
        counts[parts[1]] += 2
        counts[parts[2]] += 1
    return [lane for lane, _ in counts.most_common(3)]


def _one_is_supported(picks, head):
    total = 0
    with_one = 0
    for row in picks:
        parts = _combo_parts(row)
        if not parts or parts[0] != head:
            continue
        total += 1
        if 1 in parts[1:]:
            with_one += 1
    return total > 0 and with_one >= max(1, total // 2)


def _metric_snapshot(analysis, lane):
    source = _inputs_by_lane(analysis).get(lane, {})
    scored = _scored_by_lane(analysis).get(lane, {})
    components = scored.get("components") or {}
    return {
        "course": int(source.get("predicted_course") or source.get("course") or lane),
        "ex_st": _num(source.get("exhibition_st")),
        "avg_st": _num(source.get("avg_st")),
        "ex_time": _num(source.get("exhibition_time")),
        "motor2": _num(source.get("motor_top2_rate")),
        "motor3": _num(source.get("motor_top3_rate")),
        "start_component": _num(components.get("start")),
        "motor_component": _num(components.get("motor")),
        "ex_component": _num(components.get("exhibition")),
    }


def _head_reason(analysis, head):
    heads = analysis.get("heads") or {}
    ranked = sorted(
        ((int(lane), _num(value, 0.0)) for lane, value in heads.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    target = next((value for lane, value in ranked if lane == head), None)
    if target is None:
        return None
    text = f"{_lane_text(head)}の1着評価 {target * 100:.1f}%"
    if ranked:
        top_lane, top_value = ranked[0]
        if top_lane != head:
            text += f"（全体トップは{_lane_text(top_lane)} {top_value * 100:.1f}%）"
        elif len(ranked) > 1:
            text += f" / 次点{_lane_text(ranked[1][0])} {ranked[1][1] * 100:.1f}%"
    return text


def _data_reason(analysis, head):
    snap = _metric_snapshot(analysis, head)
    pieces = []
    if snap["course"] != head:
        pieces.append(f"展示進入は{snap['course']}コース想定")
    if snap["ex_st"] is not None:
        pieces.append(f"展示ST {snap['ex_st']:.2f}")
    elif snap["avg_st"] is not None:
        pieces.append(f"平均ST {snap['avg_st']:.2f}")
    if snap["ex_time"] is not None:
        pieces.append(f"展示タイム {snap['ex_time']:.2f}")
    if snap["motor2"] is not None:
        pieces.append(f"モーター2連率 {snap['motor2']:.1f}%")
    if not pieces:
        # Scored components are normalized model values, so label them as model
        # evaluation instead of pretending they are raw official statistics.
        ranked_components = [
            ("スタート", snap["start_component"]),
            ("モーター", snap["motor_component"]),
            ("展示", snap["ex_component"]),
        ]
        ranked_components = [(name, value) for name, value in ranked_components if value is not None]
        ranked_components.sort(key=lambda item: item[1], reverse=True)
        pieces = [f"モデル{name}評価 {value:.2f}" for name, value in ranked_components[:2]]
    return " / ".join(pieces) if pieces else None


def _water_reason(analysis):
    preview = analysis.get("preview") or {}
    wind = _num(preview.get("wind_speed"))
    wave = _num(preview.get("wave_cm"))
    pieces = []
    if wind is not None:
        pieces.append(f"風 {wind:g}m")
    if wave is not None:
        pieces.append(f"波 {wave:g}cm")
    if not pieces:
        return None
    text = " / ".join(pieces)
    if wind is not None and wind >= 4:
        text += "。風が強めなので①絶対視を少し下げ、センター〜外の攻めも残す"
    return text


def strategy_text(analysis, picks, kind):
    if not picks:
        return "展開予想：該当する配当帯に、展開と確率の両方が噛み合う候補なし。今回は見送り寄り。"

    head = _primary_head(picks)
    if head is None:
        return "展開予想：買い目候補はあるが、1着シナリオを一本化できず。検証優先。"

    support = _support_lanes(picks, head)
    support_text = "・".join(_lane_text(x) for x in support[:3]) or "相手艇"
    keep_one = _one_is_supported(picks, head)
    snap = _metric_snapshot(analysis, head)
    course = snap["course"]

    if head == 1:
        scenario = (
            "①が1Mを先に回って逃げ切る流れを軸。"
            f"ただし相手は{support_text}の攻め・追走で入れ替わる想定で、"
            "『①頭は堅いが2・3着が荒れる』形を狙う。"
        )
    elif head == 2:
        scenario = (
            "②が1Mで①の内懐を突いて先に抜ける流れを本線想定。"
            f"2・3着は{support_text}を中心に、"
            + ("①の残り目も厚く残す。" if keep_one else "①が着外まで崩れる形も拾う。")
        )
    elif head == 3:
        scenario = (
            "③がセンターから先に仕掛け、まくり差し〜攻め切りで頭まで届く流れを想定。"
            f"その攻めに連動する{support_text}を2・3着の中心に置き、"
            + ("①の残しも組み合わせる。" if keep_one else "内2艇が崩れる決着まで見る。")
        )
    elif head == 4:
        attack = "カド" if course == 4 else f"{course}コース"
        scenario = (
            f"④が{attack}から先制して1Mの主導権を取る流れを想定。"
            f"④の攻めに乗る{support_text}を相手本線にし、"
            + ("①が残すパターンも消さない。" if keep_one else "①飛びの高配当側まで狙う。")
        )
    elif head == 5:
        scenario = (
            "内〜センターの攻め合いでターン出口が空き、⑤が外から展開を拾って先頭へ出る流れを想定。"
            f"続く{support_text}との連動を重視し、外決着まで拾う。"
        )
    else:
        scenario = (
            "内側の攻め合い・ターン流れを⑥が最外から拾い、差し場を突いて頭まで届く大波乱を想定。"
            f"相手は{support_text}を中心に、展開連動型の組み合わせに限定する。"
        )

    data = _data_reason(analysis, head)
    if data:
        scenario += f" 根拠データは{_lane_text(head)}：{data}。"
    return "展開予想：" + scenario


def reason_lines(analysis, picks, kind):
    if not picks:
        label = "12〜80倍" if kind == "mid" else "50倍以上"
        return [f"{label}の候補を確認したが、展開と確率が噛み合う買い目なし"]

    head = _primary_head(picks)
    reasons = []
    if head is not None:
        head_reason = _head_reason(analysis, head)
        if head_reason:
            reasons.append("展開の軸：" + head_reason)
        data = _data_reason(analysis, head)
        if data:
            reasons.append(f"{_lane_text(head)}の材料：{data}")
        support = _support_lanes(picks, head)
        if support:
            reasons.append(
                "相手構成：" + "・".join(_lane_text(x) for x in support[:3])
                + "が選択買い目の2・3着に多く、頭シナリオとの連動を重視"
            )

    water = _water_reason(analysis)
    if water:
        reasons.append("水面：" + water)

    odds = [_num(row.get("odds")) for row in picks]
    odds = [value for value in odds if value is not None and value > 0]
    evs = []
    for row in picks:
        value = _num(row.get("expected_value"))
        if value is None:
            probability = _num(row.get("probability"))
            odd = _num(row.get("odds"))
            if probability is not None and odd is not None:
                value = probability * odd
        if value is not None:
            evs.append(value)
    if odds:
        text = f"配当は結果条件：{min(odds):.1f}〜{max(odds):.1f}倍"
        if evs:
            text += f" / 最大EV {max(evs):.2f}"
        text += "。人気薄だからではなく、上の展開に合う候補だけを採用"
        reasons.append(text)

    return reasons[:5]


def install(opportunity_alerts_module):
    """Replace only user-facing rationale; do not touch selection/scoring."""
    opportunity_alerts_module._strategy_text = strategy_text
    opportunity_alerts_module._reason_lines = reason_lines
