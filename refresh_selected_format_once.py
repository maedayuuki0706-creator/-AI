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
        main_text = "\\n".join(f"`{pick}`" for pick in main) or "なし"
        cover_text = "\\n".join(f"`{pick}`" for pick in cover) or "なし"

        selected_bets = [
            bet for bet in (record.get("virtual_bets") or [])
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

        return (
            f"{intro}\\n\\n"
            f"{title}\\n"
            f"**【{record.get('venue')} {record.get('rno')}R】**\\n"
            f"⏰ 締切 **{record.get('deadline')}**　⭐ **{score}/100**　評価 **{record.get('grade')}**\\n"
            f"━━━━━━━━━━━━\\n"
            f"🎯 **本線**\\n{main_text}\\n\\n"
            f"🛡️ **押さえ**\\n{cover_text}\\n"
            f"━━━━━━━━━━━━\\n"
            f"👀 **頭候補**\\n{head_line}\\n\\n"
            f"💡 **厳選ポイント**\\n"
            f"・総合スコア75点以上\\n"
            f"・展示6艇確認済み\\n"
            f"・仮想投票条件クリア\\n\\n"
            f"📈 **期待値候補**\\n{ev_text}\\n\\n"
            f"📊 **評価メモ**\\n{detail}"
        )
'''

path.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
print("selected prediction format refreshed")
