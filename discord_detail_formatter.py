from discord_formation import formation_summary, formation_lines


def finish_probabilities(trifecta):
    probs = {i: {"first": 0.0, "second": 0.0, "third": 0.0} for i in range(1, 7)}
    for row in trifecta or []:
        try:
            a, b, c = [int(x) for x in row["combination"].split("-")]
            p = float(row["probability"])
        except Exception:
            continue
        probs[a]["first"] += p
        probs[b]["second"] += p
        probs[c]["third"] += p
    return probs


def confidence_grade(confidence):
    if confidence is None:
        return "補完"
    if confidence >= 0.78:
        return "A"
    if confidence >= 0.63:
        return "B"
    if confidence >= 0.52:
        return "C"
    return "D"


def scenario_text(probs):
    if not probs:
        return "公式フォーカスを補完利用。独自AI用の構造化データは不足。"
    ranked = sorted(((v["first"], lane) for lane, v in probs.items()), reverse=True)
    _, first_lane = ranked[0]
    _, second_lane = ranked[1]
    if first_lane == 1:
        return f"本線は1号艇の逃げ。対抗は{second_lane}号艇の頭まで警戒。"
    if first_lane in (2, 3):
        return f"{first_lane}号艇の差し・まくり差しを高評価。1号艇残りとの組み合わせを重視。"
    return f"{first_lane}号艇の外攻めを最上位評価。内崩れの展開を警戒。"


def format_detailed_message(venue, rno, deadline, picks, exhibition, source, confidence, result=None, boats=None):
    main = picks[:3]
    cover = picks[3:6]
    lines = [
        "🚤 **競艇AIナビ｜直前予想**",
        f"**{venue} {rno}R**　締切予定 **{deadline}**",
        f"予想：**{source}** / 展示：{'取得確認' if exhibition else '未確認'} / 信頼度：**{confidence_grade(confidence)}**",
        "",
    ]
    lines += formation_lines(formation_summary(main, cover, picks[6:8]))

    if result and boats:
        probs = finish_probabilities(result.get("trifecta", []))
        lines += ["", "**🤖 AI解説**", scenario_text(probs)]
        if confidence is not None:
            lines.append(f"モデル信頼度：{round(float(confidence) * 100)}%")
        lines += ["", "**📊 AI着順確率**"]
        for lane in range(1, 7):
            p = probs[lane]
            lines.append(f"{lane}号艇｜1着 {p['first']*100:.1f}% / 2着 {p['second']*100:.1f}% / 3着 {p['third']*100:.1f}%")

        lines += ["", "**🧾 根拠データ**"]
        for b in boats:
            fmark = " F持ち" if b.get("flying") else ""
            lines.append(
                f"{b['lane']}号艇{fmark}｜全国 {float(b.get('win_rate') or 0):.2f} / 当地 {format(float(b['local_win_rate']), '.2f') if b.get('local_win_rate') is not None else '未取得'} "
                f"/ ST {float(b.get('avg_st',0)):.2f} / M2連 {float(b.get('motor_top2_rate',0)):.1f}%"
            )
        scored = result.get("boats", [])
        if scored:
            lines += ["", "**🔍 AI評価順位**"]
            for rank, row in enumerate(scored[:3], 1):
                lines.append(f"{rank}位：{row['lane']}号艇　総合スコア {float(row['score']):.3f}")
    else:
        lines += ["", "**🤖 AI解説**", "独自AI用データ不足のため公式フォーカスを補完利用。結果は独自AIと分けて学習します。"]

    lines += ["", "※予想根拠はBOAT RACE公式当日データ＋競艇AIナビ評価モデル。結果は毎日照合して学習へ反映。"]
    return "\n".join(lines)
