"""Explain why support boats are kept or pruned, and measure ticket compression.

Shared by the existing and experimental Hiyori streams so A/B comparisons use
the same yardstick.  This module does not change prediction probabilities.
"""
from __future__ import annotations

LEVELS = (20, 16, 12, 10, 8, 6, 4)

def position_marginals(analysis):
    out={p:{lane:0.0 for lane in range(1,7)} for p in (1,2,3)}
    for row in analysis.get("trifecta",[]):
        parts=str(row.get("combination","")).split("-")
        if len(parts)!=3: continue
        prob=float(row.get("probability") or 0.0)
        for i,lane in enumerate(parts,1):
            try: out[i][int(lane)]+=prob
            except ValueError: pass
    return out

def support_decisions(analysis):
    m=position_marginals(analysis)
    heads=analysis.get("heads") or m[1]
    head=max(heads,key=heads.get) if heads else None
    decisions=[]
    for lane in range(1,7):
        if lane==int(head) if head is not None else False: continue
        p2=m[2][lane]; p3=m[3][lane]; support=p2+p3
        boat=next((b for b in analysis.get("inputs",[]) if int(b.get("lane",0))==lane),{})
        evidence=[]
        if p2>=.18: evidence.append("2着期待が高い")
        if p3>=.18: evidence.append("3着期待が高い")
        if boat.get("exhibition_grade") is not None and float(boat.get("exhibition_grade") or 0)>=.65: evidence.append("展示気配○")
        if boat.get("motor_top2_rate") is not None and float(boat.get("motor_top2_rate") or 0)>=40: evidence.append("モーター○")
        if support>=.30:
            action="残す"; reason="・".join(evidence or ["連対候補として確率を確保"])
        elif support>=.20:
            action="3着中心"; reason="2着評価は低め、3着まで残す" if p3>=p2 else "相手候補だが優先度は低め"
        else:
            action="削り候補"; reason="2・3着の合算評価が低い"
        decisions.append({"lane":lane,"action":action,"reason":reason,"p2":round(p2,4),"p3":round(p3,4)})
    return decisions

def compression_snapshot(analysis):
    rows=list(analysis.get("trifecta") or [])
    heads=analysis.get("heads") or {}
    head=max(heads,key=heads.get) if heads else (rows[0]["combination"].split("-")[0] if rows else None)
    head_rows=[r for r in rows if str(r.get("combination","")).split("-")[0]==str(head)]
    return {
        "head":int(head) if head is not None else None,
        "levels":{str(n):[r["combination"] for r in head_rows[:n]] for n in LEVELS},
        "support_decisions":support_decisions(analysis),
        "metric_version":"compression-v1",
    }

def format_support_note(analysis):
    snap=compression_snapshot(analysis)
    lines=["","**🔗 紐の残し・削り理由**"]
    for d in snap["support_decisions"]:
        lines.append(f"{d['lane']}号艇｜{d['action']}：{d['reason']}（2着 {d['p2']*100:.1f}% / 3着 {d['p3']*100:.1f}%）")
    lines.append("✂️ 圧縮検証：頭-全-全20点 → 16 → 12 → 10 → 8 → 6 → 4点を結果照合")
    return "\n".join(lines)
