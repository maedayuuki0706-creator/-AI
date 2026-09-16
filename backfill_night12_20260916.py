"""One-off retrospective replay for missed night 12R opportunity feeds on 2026-09-16.

This does not append to live prediction logs or hit statistics. The races have
already closed, so official odds may be final rather than the exact pre-deadline
snapshot. Messages are clearly labelled retrospective/reference-only.
"""
from __future__ import annotations

import detailed_discord_notify as app
import opportunity_alerts
import opportunity_scenario_commentary

DAY = "20260916"
TARGETS = [
    ("12", 12, "20:30"),  # 住之江
    ("19", 12, "20:45"),  # 下関
]


def main() -> int:
    opportunity_scenario_commentary.install(opportunity_alerts)
    sent = 0

    for jcd, rno, deadline in TARGETS:
        venue = app.base.VENUES[jcd]
        analysis = app.base.analyze_official(DAY, jcd, rno)
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
                "※ライブ配信漏れ確認用です。現在取得できる公式展示・オッズで再計算しているため、"
                "当日の正式実績・的中率・回収率には加算しません。\n\n"
            )
            opportunity_alerts._send(env_name, notice + payload["message"])
            sent += 1

    print(f"night 12R retrospective messages sent: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
