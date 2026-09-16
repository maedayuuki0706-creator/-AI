from pathlib import Path
import re

FILES = [
    Path("opportunity_alerts.py"),
    Path("send_opportunity_daily_discord.py"),
]

for path in FILES:
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    # Rename only the standalone longshot label; keep 中穴AI unchanged.
    text = re.sub(r"(?<!中)穴AI", "穴予想", text)
    text = text.replace("｜的中だけ軽く", "")
    text = text.replace("穴予想は的中したレースだけ🚨形式で軽く掲載。", "穴予想は的中レースのみ掲載。")

    if path.name == "send_opportunity_daily_discord.py":
        old = (
            '            lines += ["", "**💣 穴予想**"]\n'
            '            for rno, winner, payout in sorted(long_hits[jcd]):\n'
            '                lines += [f"{venue} {rno}レース", f"{winner}　🚨{payout:,}円的中🎯🚨"]\n'
        )
        new = (
            '            lines += ["", "**💣 穴予想**"]\n'
            '            for rno, winner, payout in sorted(long_hits[jcd]):\n'
            '                lines += [\n'
            '                    f"【{venue} {rno}レース】",\n'
            '                    f"買い目：{winner}",\n'
            '                    f"払戻金：{payout:,}円的中🎯",\n'
            '                ]\n'
        )
        text = text.replace(old, new)

    path.write_text(text, encoding="utf-8")
    print(f"updated {path}")
