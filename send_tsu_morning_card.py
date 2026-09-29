"""Send BOAT RACE Tsu 2026-09-30 morning race card to Discord.

Marks notable motors from recent Tsu form:
◎ 67 / 31 / 51
○ 63 / 54
"""
from __future__ import annotations

import argparse
from datetime import datetime
import os
import time

import direct_discord_notify as base

TARGET_DAY = os.getenv("TSU_TARGET_DAY", "20260930").strip()
JCD = "09"
STRONG = {67, 31, 51}
WATCH = {63, 54}


def mark_motor(number: int | None) -> str:
    if number in STRONG:
        return "◎"
    if number in WATCH:
        return "○"
    return ""


def boat_text(boat: dict) -> str:
    lane = int(boat["lane"])
    circled = "①②③④⑤⑥"[lane - 1]
    motor = boat.get("motor_number")
    m2 = boat.get("motor_top2_rate")
    mark = mark_motor(motor)
    motor_text = f"M{motor}{mark}" if motor is not None else "M-"
    if m2 is not None:
        motor_text += f"({float(m2):.1f}%)"
    return f"{circled}{boat.get('name','-')} {boat.get('current_class','-')} {motor_text}"


def build_messages(day: str) -> list[str]:
    base.fetch.cache_clear()
    times = base.deadlines(day, JCD)
    if len(times) != 12:
        times = ["--:--"] * 12

    races: list[str] = []
    for rno in range(1, 13):
        boats = base.parse_racelist_boats(day, JCD, rno)
        if len(boats) != 6:
            races.append(f"**{rno}R {times[rno-1]}**\n出走表を取得できませんでした")
            continue
        lines = [boat_text(boat) for boat in boats]
        races.append(f"**{rno}R {times[rno-1]}**\n" + "\n".join(lines))

    header = (
        f"🚤 **津｜{day[4:6]}/{day[6:8]} 出走表**\n"
        "注目モーター印：**◎ 67・31・51 / ○ 63・54**\n"
        "◎＝直近実績を強めに評価　○＝穴候補として注目\n"
        "※モーター2連率は朝時点の公式出走表表示値"
    )

    messages: list[str] = []
    current = header
    for block in races:
        candidate = current + "\n\n" + block
        if len(candidate) > 1850 and current != header:
            messages.append(current)
            current = "🚤 **津｜出走表 続き**\n" + block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.now(base.JST)
    if not args.dry_run and now.strftime("%Y%m%d") != TARGET_DAY:
        print(f"skip: today={now:%Y%m%d} target={TARGET_DAY}")
        return 0

    messages = build_messages(TARGET_DAY)
    if args.dry_run:
        for i, message in enumerate(messages, 1):
            print(f"--- message {i}/{len(messages)} ---")
            print(message)
        return 0

    for message in messages:
        base.send_discord(message)
        time.sleep(0.7)
    print(f"sent Tsu morning card: {len(messages)} message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
