"""Discord entry point for Boat AI Navi.

The existing near-deadline notifier remains the stable core. This wrapper now
also sends one all-race morning briefing per day and appends odds-aware virtual
betting allocations to the normal race messages.

Live prediction cards use a variable 6-14 point width. The original six picks
remain the core; extra points are used mainly to widen second/third-place ties
so near-miss races caused by a missing supporting boat are covered more often.

From 2026-09-15, the notifier also emits two additive streams without reducing
normal coverage:
- selected-race alerts for strong A/B final predictions with a meaningful EV edge
- special longshot alerts for 100x+ core bets that still have model/EV support
"""
import os
import sys

import direct_discord_notify as base
import x_post_delivery
import morning_all_races_discord as morning
from virtual_betting import allocate_virtual_bets, compact_virtual_text


_ORIGINAL_ANALYSIS_MESSAGE = base.make_analysis_message
_ORIGINAL_LOG_PREDICTION = base.log_prediction
_ORIGINAL_DISPLAYED_PICKS = base.displayed_picks
_VIRTUAL = {}


def _position_gap(analysis, position):
    """Return the gap between the two most likely boats at one finish position."""
    totals = {lane: 0.0 for lane in range(1, 7)}
    for row in analysis.get("trifecta", []):
        try:
            lane = int(row["combination"].split("-")[position])
            totals[lane] += float(row.get("probability") or 0.0)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    ranked = sorted(totals.values(), reverse=True)
    return (ranked[0] - ranked[1]) if len(ranked) >= 2 else 1.0


def _target_point_count(analysis):
    """Choose 6-14 points, expanding when the predicted order is less certain."""
    grade = analysis.get("grade")
    head_gap = _position_gap(analysis, 0)
    second_gap = _position_gap(analysis, 1)
    third_gap = _position_gap(analysis, 2)

    target = 6 if grade == "A" else 8 if grade == "B" else 10
    if head_gap < 0.10:
        target += 2
    if second_gap < 0.08:
        target += 2
    if third_gap < 0.07:
        target += 2
    return max(6, min(14, target))


def _conviction_heads(analysis):
    """Choose 1-2 winner axes, with a rare three-head exception for true ties."""
    ranked = sorted(
        (analysis.get("heads") or {}).items(),
        key=lambda item: float(item[1] or 0.0),
        reverse=True,
    )
    if not ranked:
        return []
    primary = (str(ranked[0][0]), float(ranked[0][1] or 0.0))
    out = [primary]
    if len(ranked) < 2:
        return out

    second = (str(ranked[1][0]), float(ranked[1][1] or 0.0))
    top = primary[1]
    second_value = second[1]
    ratio = 0.68 if analysis.get("balanced_head_mode") else 0.72
    if top > 0 and (second_value >= top * ratio or (top - second_value) <= 0.065):
        out.append(second)

    # Three heads are allowed only when the model itself cannot separate them.
    # This is the "345-12=345" type of race: coherent mixed formation, not spray.
    if len(out) >= 2 and len(ranked) >= 3 and top > 0:
        third = (str(ranked[2][0]), float(ranked[2][1] or 0.0))
        tight_ratio = 0.82 if analysis.get("balanced_head_mode") else 0.86
        tight_gap = 0.050 if analysis.get("balanced_head_mode") else 0.040
        if third[1] >= top * tight_ratio and (top - third[1]) <= tight_gap:
            out.append(third)
    return out


def _row_probability(row):
    try:
        return float(row.get("probability") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _prefix(row):
    parts = str(row.get("combination") or "").split("-")
    return "-".join(parts[:2]) if len(parts) == 3 else ""


def _best_prefix(rows, head):
    masses = {}
    for row in rows:
        parts = str(row.get("combination") or "").split("-")
        if len(parts) != 3 or parts[0] != str(head):
            continue
        key = f"{parts[0]}-{parts[1]}"
        masses[key] = masses.get(key, 0.0) + _row_probability(row)
    return max(masses, key=masses.get) if masses else None


def _best_second_hubs(rows, allowed_heads, limit=2):
    masses = {}
    allowed = {str(head) for head in allowed_heads}
    for row in rows:
        parts = str(row.get("combination") or "").split("-")
        if len(parts) != 3 or parts[0] not in allowed:
            continue
        second = parts[1]
        masses[second] = masses.get(second, 0.0) + _row_probability(row)
    return [
        lane for lane, _ in sorted(
            masses.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:limit]
    ]


def _append_unique(selected, seen, row):
    combo = str(row.get("combination") or "")
    if not combo or combo in seen:
        return False
    selected.append(row)
    seen.add(combo)
    return True


def _conviction_picks(analysis, target):
    """Hit-rate-first card: strong heads first, then extend their tails.

    Default is one or two heads. A third head is permitted only in a true model
    tie, and then the card is organized around two strong second-place hubs
    rather than scattered singletons.
    """
    rows = list(analysis.get("trifecta") or [])
    if not rows:
        return []

    heads = _conviction_heads(analysis)
    if not heads:
        return rows[:target]

    allowed_heads = [lane for lane, _ in heads]
    primary = allowed_heads[0]
    secondary = allowed_heads[1] if len(allowed_heads) > 1 else None
    tertiary = allowed_heads[2] if len(allowed_heads) > 2 else None

    # Keep 6-14 as the normal range. Only a genuine three-head tie may expand
    # slightly, capped at 16, because otherwise the formation loses conviction.
    if tertiary:
        target = min(16, max(12, int(target) + 2))

    main_prefix = _best_prefix(rows, primary)
    reciprocal_prefix = f"{secondary}-{primary}" if secondary else None
    second_hubs = _best_second_hubs(rows, allowed_heads, limit=2) if tertiary else []

    analysis["conviction_structure"] = {
        "primary_head": primary,
        "secondary_head": secondary,
        "tertiary_head": tertiary,
        "main_prefix": main_prefix,
        "reciprocal_prefix": reciprocal_prefix,
        "second_hubs": second_hubs,
        "max_heads": len(allowed_heads),
        "target_points": int(target),
        "policy": "conviction-heads-v2-mixed-exception",
    }

    selected = []
    seen = set()

    if tertiary and second_hubs:
        # Mixed race: seed one strong hub-based ticket per head, then keep the
        # remaining budget inside the same head/hub structure.
        for head in allowed_heads:
            for row in rows:
                parts = str(row.get("combination") or "").split("-")
                if len(parts) == 3 and parts[0] == head and parts[1] in second_hubs:
                    if _append_unique(selected, seen, row):
                        break
        for row in rows:
            parts = str(row.get("combination") or "").split("-")
            if len(parts) != 3:
                continue
            if parts[0] in allowed_heads and parts[1] in second_hubs:
                _append_unique(selected, seen, row)
                if len(selected) >= target:
                    return selected[:target]
    else:
        # Normal race: first three tickets tell one clear ordered-pair story.
        if main_prefix:
            main_rows = [row for row in rows if _prefix(row) == main_prefix]
            for row in main_rows[:3]:
                _append_unique(selected, seen, row)

        for row in rows:
            if len(selected) >= min(3, target):
                break
            parts = str(row.get("combination") or "").split("-")
            if len(parts) == 3 and parts[0] == primary:
                _append_unique(selected, seen, row)

    # Tail extension gets priority over spraying extra winner candidates.
    priority_prefixes = []
    if main_prefix:
        priority_prefixes.append(main_prefix)
    if secondary:
        direct = f"{primary}-{secondary}"
        reverse = f"{secondary}-{primary}"
        for pref in (direct, reverse):
            if pref not in priority_prefixes:
                priority_prefixes.append(pref)
        second_best = _best_prefix(rows, secondary)
        if second_best and second_best not in priority_prefixes:
            priority_prefixes.append(second_best)

    for pref in priority_prefixes:
        pref_rows = [row for row in rows if _prefix(row) == pref]
        if not pref_rows:
            continue
        best = max((_row_probability(row) for row in pref_rows), default=0.0)
        floor = max(0.004, best * 0.50)
        for row in pref_rows:
            if _row_probability(row) < floor:
                continue
            _append_unique(selected, seen, row)
            if len(selected) >= target:
                return selected[:target]

    # Fill the remaining budget only with the declared heads.
    for row in rows:
        parts = str(row.get("combination") or "").split("-")
        if len(parts) != 3 or parts[0] not in allowed_heads:
            continue
        _append_unique(selected, seen, row)
        if len(selected) >= target:
            return selected[:target]

    # Defensive fallback; normally unreachable. Do not introduce a new head
    # outside the declared conviction structure unless source data is incomplete.
    for row in rows:
        _append_unique(selected, seen, row)
        if len(selected) >= target:
            break
    return selected[:target]


def displayed_picks_variable(analysis, required):
    """Build a clear 1-2 head card, then spend extra points on tail coverage."""
    core = list(_ORIGINAL_DISPLAYED_PICKS(analysis, required))
    if not required or len(core) < 6:
        return core

    target = _target_point_count(analysis)
    if analysis.get("balanced_head_mode"):
        target = max(10, target)
    return _conviction_picks(analysis, target)


def analysis_message_with_virtual(day, jcd, rno, deadline, phase, analysis, rows, required):
    message = _ORIGINAL_ANALYSIS_MESSAGE(day, jcd, rno, deadline, phase, analysis, rows, required)

    structure = analysis.get("conviction_structure") or {}
    primary = structure.get("primary_head")
    secondary = structure.get("secondary_head")
    if primary:
        tertiary = structure.get("tertiary_head")
        if tertiary:
            axis_line = f"🎯 頭候補：**{primary}・{secondary}・{tertiary}号艇**　🌪️混戦"
        else:
            axis_line = f"🎯 軸：**{primary}号艇**"
            if secondary:
                axis_line += f"　⚔️ 逆転候補：**{secondary}号艇**"
        marker = "**3連単フォーメーション**"
        if marker in message:
            message = message.replace(marker, axis_line + "\n\n" + marker, 1)
        elif axis_line not in message:
            message = axis_line + "\n" + message

    allocation = allocate_virtual_bets(rows[:6])
    _VIRTUAL[(day, jcd, int(rno), phase)] = allocation
    if allocation.get('status') != 'bet':
        message = (f"{base.VENUES.get(jcd, jcd)} {rno}レース\n見送り推奨\n"
                   f"理由：{allocation.get('reason') or '仮想投票の条件未達'}\n\n" + message)
    extra = "\n\n**仮想投票（1口=100円）**\n" + compact_virtual_text(allocation)
    extra += "\n日次集計は締切前の最新配信で差替え（追加投票なし）。"

    if len(message) + len(extra) > 1950:
        lines = message.splitlines()
        if lines and lines[-1].startswith("http"):
            message = "\n".join(lines[:-1])
    if len((message + extra).encode('utf-16-le')) // 2 > 1950:
        start = message.find('**判断材料（6艇）**')
        end = message.find('風速 ', start)
        if start >= 0 and end > start:
            message = message[:start] + message[end:]
    if len((message + extra).encode('utf-16-le')) // 2 > 2000:
        raise ValueError('Prediction and exact allocation exceed Discord limit')
    return message + extra


def _record_bets(record):
    return list(record.get("virtual_bets") or [])


def _selected_bets(record):
    """EV-backed bets strong enough to justify the separate selected-race feed."""
    return [
        bet for bet in _record_bets(record)
        if float(bet.get("expected_value") or 0) >= 1.15
        and float(bet.get("probability") or 0) >= 0.015
    ]


def _is_selected_record(record):
    return (
        record.get("phase") == "final"
        and bool(record.get("exhibition"))
        and record.get("grade") in {"A", "B"}
        and bool(_selected_bets(record))
    )


def _selected_message(record):
    heads = record.get("heads") or {}
    ranked = sorted(heads.items(), key=lambda item: float(item[1]), reverse=True)
    top_text = ""
    if ranked:
        top_text = f"\n頭評価：{ranked[0][0]}号艇 {float(ranked[0][1]) * 100:.1f}%"
        if len(ranked) > 1:
            top_text += f" / 対抗{ranked[1][0]}号艇 {float(ranked[1][1]) * 100:.1f}%"
    bets = _selected_bets(record)
    ev_text = " / ".join(
        f"{b['combination']} {float(b.get('odds') or 0):.1f}倍 EV{float(b.get('expected_value') or 0):.2f}"
        for b in bets[:3]
    )
    main = " / ".join(record.get("main") or []) or "-"
    cover = " / ".join((record.get("cover") or [])[:6]) or "-"
    return (
        f"🔥 **厳選予想｜{record.get('venue')} {record.get('rno')}R**\n"
        f"締切 **{record.get('deadline')}** / 評価 **{record.get('grade')}** / 展示反映済み"
        f"{top_text}\n"
        f"◎ 本線：{main}\n"
        f"○ 押さえ：{cover}\n"
        f"選定理由：A/B評価＋展示確定＋確率/EV条件クリア\n"
        f"EV候補：{ev_text}"
    )


def _send_selected_discord(content):
    """Send selected-race alerts only to the dedicated Discord channel."""
    selected_url = os.getenv("DISCORD_SELECTED_WEBHOOK_URL", "").strip()
    if not selected_url:
        raise RuntimeError("DISCORD_SELECTED_WEBHOOK_URL is missing")

    original = os.environ.get("DISCORD_WEBHOOK_URL")
    os.environ["DISCORD_WEBHOOK_URL"] = selected_url
    try:
        base.send_discord(content, notify_everyone=True)
    finally:
        if original is None:
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
        else:
            os.environ["DISCORD_WEBHOOK_URL"] = original


def _longshot_bets(record):
    """Longshots must already be in the six core bets; no extra spray is added."""
    return [
        bet for bet in _record_bets(record)
        if float(bet.get("odds") or 0) >= 100.0
        and float(bet.get("expected_value") or 0) >= 1.25
        and float(bet.get("probability") or 0) >= 0.010
    ]


def _longshot_message(record):
    bets = _longshot_bets(record)
    if not bets:
        return None

    grouped = {}
    for bet in bets:
        combo = str(bet.get("combination") or "")
        parts = combo.split("-")
        if len(parts) != 3:
            continue
        grouped.setdefault(f"{parts[0]}-{parts[1]}", []).append(bet)

    lines = [
        f"🚨 **万舟警報｜{record.get('venue')} {record.get('rno')}R** 🚨",
        f"締切 **{record.get('deadline')}** / 評価 {record.get('grade') or '混戦'} / 展示反映済み",
    ]
    for prefix, rows in grouped.items():
        if len(rows) >= 2:
            lines.append(f"**{prefix}-○○**")
        else:
            lines.append(f"**{rows[0]['combination']}**")
        lines.append("候補：" + " / ".join(
            f"{b['combination']}（{float(b.get('odds') or 0):.1f}倍・EV{float(b.get('expected_value') or 0):.2f}）"
            for b in rows
        ))
    lines.append("根拠：通常の本線を削らず、コア買い目の中で100倍超＋確率/EV条件を満たした時だけ発令。")
    return "\n".join(lines)


def log_prediction_with_virtual(record):
    key = (record.get("day"), str(record.get("jcd")), int(record.get("rno", 0)), record.get("phase", "final"))
    allocation = _VIRTUAL.get(key)
    if allocation is not None:
        record = dict(record)
        record["virtual_bets"] = allocation.get("bets", [])
        record["virtual_total_units"] = allocation.get("total_units", 0)
        record["virtual_min_return_units"] = allocation.get("min_return_units")
        record["virtual_status"] = allocation.get("status")
        record["virtual_unit_yen"] = 100
        record["virtual_selection_rule"] = "latest_pre_deadline_per_race"
        record["prediction_point_policy"] = "conviction_heads_tail_extension_v2"

    _ORIGINAL_LOG_PREDICTION(record)

    if record.get("phase") != "final":
        return
    try:
        if _is_selected_record(record):
            _send_selected_discord(_selected_message(record))
            try:
                x_post_delivery.send_selected_record(record)
            except Exception as exc:
                print(f"x draft failed selected {record.get('jcd')} {record.get('rno')}R: {type(exc).__name__}")
    except Exception as exc:
        print(f"selected alert failed {record.get('jcd')} {record.get('rno')}R: {type(exc).__name__}")
    try:
        longshot = _longshot_message(record)
        if longshot:
            base.send_discord(longshot)
    except Exception as exc:
        print(f"longshot alert failed {record.get('jcd')} {record.get('rno')}R: {type(exc).__name__}")


def _all_races_every_day(policy, day, jcd):
    """Keep near-deadline final updates active for every venue every day."""
    return True


def main():
    base.displayed_picks = displayed_picks_variable
    base.make_analysis_message = analysis_message_with_virtual
    base.log_prediction = log_prediction_with_virtual
    base.required_venue = _all_races_every_day
    result = base.main()
    if "--test" not in sys.argv and "--dry-run" not in sys.argv:
        morning.run_once()
    return result


if __name__ == "__main__":
    sys.exit(main())
