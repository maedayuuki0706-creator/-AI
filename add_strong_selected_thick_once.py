from pathlib import Path

path = Path("selection_scoring.py")
text = path.read_text(encoding="utf-8")
start = text.index("    def selected_message(record):\n")
end = text.index("\n    def scored_log(record):\n", start)

new_block = '''    def selected_message(record):
        score = int(record.get("selection_score") or 0)
        strong = score >= 85
        title = "🔥🔥 **厳選くんの勝負レース【強厳選】**" if strong else "🔥 **厳選くんの勝負レース**"
        intro = random.choice(GENSEN_KUN_LINES)

        heads = record.get("heads") or {}
        ranked = sorted(heads.items(), key=lambda item: float(item[1]), reverse=True)
        head_line = "取得なし"
        if ranked:
            head_line = f"{ranked[0][0]}号艇 {float(ranked[0][1]) * 100:.1f}%"
            if len(ranked) > 1:
                head_line += f" ｜ 対抗 {ranked[1][0]}号艇 {float(ranked[1][1]) * 100:.1f}%"

        main = list(record.get("main") or [])
        cover = list((record.get("cover") or [])[:6])
        virtual_bets = list(record.get("virtual_bets") or [])
        bets_by_combo = {
            str(bet.get("combination")): bet
            for bet in virtual_bets
            if bet.get("combination")
        }

        # 強厳選だけ、本線の中から確率・EV・並び順（展開一致）を合わせて
        # 1〜3点を「厚め」として自動抽出する。
        thick = []
        if strong and main:
            ranked_main = []
            denom = max(1, len(main) - 1)
            for index, pick in enumerate(main):
                bet = bets_by_combo.get(str(pick), {})
                ev = float(bet.get("expected_value") or 0.0)
                probability = float(bet.get("probability") or 0.0)
                alignment = 1.0 - (index / denom)
                thick_score = (ev * 0.55) + (probability * 10.0 * 0.30) + (alignment * 0.15)
                ranked_main.append((thick_score, index, pick))
            ranked_main.sort(key=lambda item: (-item[0], item[1]))
            thick_count = 3 if score >= 92 else 2 if score >= 88 else 1
            thick = [item[2] for item in ranked_main[:min(thick_count, len(ranked_main))]]

        regular_main = [pick for pick in main if pick not in thick]
        thick_text = "\\n".join(f"`{pick}`" for pick in thick) or "なし"
        main_text = "\\n".join(f"`{pick}`" for pick in regular_main) or ("厚めに集約" if thick else "なし")
        cover_text = "\\n".join(f"`{pick}`" for pick in cover) or "なし"

        selected_bets = [
            bet for bet in virtual_bets
            if float(bet.get("expected_value") or 0) >= 1.15
            and float(bet.get("probability") or 0) >= 0.015
        ]
        ev_lines = [
            f"・{bet['combination']}｜{float(bet.get('odds') or 0):.1f}倍｜EV {float(bet.get('expected_value') or 0):.2f}"
            for bet in selected_bets[:3]
        ]
        ev_text = "\\n".join(ev_lines) if ev_lines else "・仮想投票条件クリア"

        bd = record.get("selection_score_breakdown") or {}
        detail = (
            f"頭 {bd.get('head', 0)}/25 ｜ 相手 {bd.get('support', 0)}/15 ｜ 展示/ST {bd.get('exhibition_st', 0)}/15\\n"
            f"選手/コース {bd.get('racer_course', 0)}/15 ｜ モーター {bd.get('motor', 0)}/10 ｜ EV {bd.get('ev', 0)}/15"
        )

        thick_section = ""
        if strong:
            thick_section = f"💥 **厚め（{len(thick)}点）**\\n{thick_text}\\n\\n"

        point_heading = "💡 **強厳選になった理由**" if strong else "💡 **厳選ポイント**"
        threshold_text = "・総合スコア85点以上" if strong else "・総合スコア75点以上"

        return (
            f"{intro}\\n\\n"
            f"{title}\\n"
            f"**【{record.get('venue')} {record.get('rno')}R】**\\n"
            f"⏰ 締切 **{record.get('deadline')}**　⭐ **{score}/100**　評価 **{record.get('grade')}**\\n"
            f"━━━━━━━━━━━━\\n"
            f"{thick_section}"
            f"🎯 **本線（{len(regular_main)}点）**\\n{main_text}\\n\\n"
            f"🛡️ **押さえ（{len(cover)}点）**\\n{cover_text}\\n"
            f"━━━━━━━━━━━━\\n"
            f"👀 **頭候補**\\n{head_line}\\n\\n"
            f"{point_heading}\\n"
            f"{threshold_text}\\n"
            f"・展示6艇確認済み\\n"
            f"・仮想投票条件クリア\\n\\n"
            f"📈 **期待値候補**\\n{ev_text}\\n\\n"
            f"📊 **評価メモ**\\n{detail}"
        )
'''

path.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
print("strong selected thick-bet format added")
