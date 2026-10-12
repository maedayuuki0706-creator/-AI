"""Yuuki's pre-race win/loss scenario notes.

Diagnostic-only: does not change bets, probabilities or delivery gates.
Never treat a single exhibition ST as the predicted race ST.
"""
from __future__ import annotations


def _num(value):
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def analyze(official):
    inputs = official.get("inputs") or []
    boats = {int(b["lane"]): b for b in inputs if isinstance(b, dict) and str(b.get("lane", "")).isdigit()}
    if len(boats) != 6:
        return {"status": "insufficient_inputs", "lanes": []}
    rows = []
    for lane in range(1, 7):
        b = boats[lane]
        st = _num(b.get("exhibition_st"))
        avg = _num(b.get("avg_st") or b.get("average_st"))
        motor = _num(b.get("motor_top2_rate"))
        inside = boats.get(lane - 1)
        outside = boats.get(lane + 1)
        inside_st = _num(inside.get("exhibition_st")) if inside else None
        outside_st = _num(outside.get("exhibition_st")) if outside else None
        wins, losses, evidence = [], [], []
        if avg is not None:
            evidence.append(f"平均ST {avg:.2f}")
        if st is not None:
            evidence.append(f"展示ST {st:.2f}")
        if motor is not None:
            evidence.append(f"モーター2連率 {motor:.1f}%")
        if lane == 1:
            wins.append("先マイできれば逃げ切る")
            losses.append("内側の差し、または外からの攻撃で先マイが崩れる")
        else:
            wins.append("スタートと行き足がそろえば攻撃または差しの機会が生まれる")
            losses.append("内側の壁を越えられず、旋回位置を失う")
        if st is not None and inside_st is not None:
            if st + 0.08 < inside_st:
                wins.append(f"展示では内隣{lane-1}号艇よりSTが0.08秒以上先行。攻めの仮説")
                losses.append("展示ST差が本番で再現されなければ攻めは不成立")
            elif inside_st + 0.08 < st:
                losses.append(f"展示では内隣{lane-1}号艇にSTで0.08秒以上後手")
        if st is not None and outside_st is not None and outside_st + 0.08 < st:
            losses.append(f"展示では外隣{lane+1}号艇が0.08秒以上先行。攻撃を受ける仮説")
        if not evidence:
            evidence.append("数値根拠未取得（仮説のみ）")
        rows.append({"lane": lane, "evidence": evidence, "win_paths": wins,
                     "loss_paths": losses, "confidence": "hypothesis_only",
                     "excluded_accidents": True})
    return {"status": "diagnostic_only", "lanes": rows,
            "limitations": ["今節平均ST・場特性・風向・チルト・足評価は未接続なら評価しない",
                            "展示STは本番STを保証しない",
                            "事故・転覆等は通常の展開負けとして学習しない"]}


def message_lines(scenarios):
    if scenarios.get("status") != "diagnostic_only":
        return ["・6艇の展開評価：データ不足"]
    lines = ["**6艇の勝ち筋／負け筋（仮説・買い目には未反映）**"]
    for row in scenarios["lanes"]:
        lines.append(f"・{row['lane']}号艇｜勝：{row['win_paths'][0]}／負：{row['loss_paths'][0]}")
    return lines
