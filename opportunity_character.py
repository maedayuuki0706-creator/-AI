"""Character voice for the 中穴 / 穴 opportunity channels.

This module changes only the user-facing tone. Selection, scoring and ticket
construction stay untouched. The selected 中穴 stream keeps the separate
厳選くん voice.
"""
from __future__ import annotations

import random


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


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
    """Install character voice while leaving selection/scoring unchanged."""
    if getattr(opportunity_alerts_module, "_character_voice_installed", False):
        return

    original_message = opportunity_alerts_module._message
    original_selected_mid = opportunity_alerts_module._selected_mid_message

    def character_message(venue, rno, deadline, analysis, picks, kind, score, breakdown):
        body = original_message(venue, rno, deadline, analysis, picks, kind, score, breakdown)
        if kind == "mid":
            intro = _mid_line(analysis, picks, score)
        else:
            intro = _long_line(analysis, picks, score)
        return f"{intro}\n\n{body}"

    def selected_mid_message(message):
        # 厳選くん already has its own character. Do not mix the 中穴 voice into it.
        return original_selected_mid(_strip_mid_character_prefix(message))

    opportunity_alerts_module._message = character_message
    opportunity_alerts_module._selected_mid_message = selected_mid_message
    opportunity_alerts_module._character_voice_installed = True
