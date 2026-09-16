"""One-off retrospective replay for missed Suminoe races on 2026-09-16.

This intentionally does NOT append to live prediction logs or hit statistics.
The official pages are fetched after the races, so odds can be final rather than
the exact pre-deadline snapshot. Every Discord card is clearly labelled as a
retrospective recalculation for reference only.
"""
from __future__ import annotations

import detailed_discord_notify as app
import opportunity_alerts
import opportunity_scenario_commentary

DAY = "20260916"
JCD = "12"
RACES = {
    5: "17:01",
    6: "17:30",
    7: "17:55",
}


def main() -> int:
    opportunity_scenario_commentary.install(opportunity_alerts)
    venue = app.base.VENUES[JCD]
    sent = 0

    for rno, deadline in RACES.items():
        analysis = app.base.analyze_official(DAY, JCD, rno)
        if not analysis:
            print(f"retrospective unavailable: {venue} {rno}R")
            continue

        for kind, env_name in (
            ("mid", "DISCORD_WEBHOOK_MID_ODDS"),
            ("long", "DISCORD_WEBHOOK_LONGSHOT"),
        ):
            payload = opportunity_alerts._build_payload(venue, rno, deadline, analysis, kind)
            notice = (
                "🔁 **締切後の遡及再計算｜参考のみ**\n"
                "※当時のライブ配信ではありません。現在取得できる公式展示・オッズで再計算しているため、"
                "実績・的中率には加算しません。\n\n"
            )
            opportunity_alerts._send(env_name, notice + payload["message"])
            sent += 1

    print(f"retrospective messages sent: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
