"""Discord daily report for 新人予想家 ゆうき (promoted PT3)."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import urllib.request
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
SCORE_ROOT = Path("data/prototype_scoreboard")
MARKER_ROOT = Path("data/yuuki_daily_report")
WEBHOOK_ENV = "PT3_DISCORD_WEBHOOK_URL"
LEGACY_WEBHOOK_ENV = "PROTO3_DISCORD_WEBHOOK_URL"


def read_json(path: Path, default=None):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError):
        return default


def webhook_url() -> str:
    return os.getenv(WEBHOOK_ENV, "").strip() or os.getenv(LEGACY_WEBHOOK_ENV, "").strip()


def post(message: str) -> None:
    url = webhook_url()
    if not url:
        raise RuntimeError(f"{WEBHOOK_ENV} / {LEGACY_WEBHOOK_ENV} is not configured")
    payload = json.dumps({
        "username": "新人予想家 ゆうき",
        "content": message,
        "allowed_mentions": {"parse": []},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "boat-ai-yuuki-report/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Discord HTTP {response.status}")


def pct(value) -> str:
    return "—" if value is None else f"{float(value):.1f}%"


def money(value) -> str:
    return f"{int(value or 0):+,}円"


def venue_lines(summary: dict) -> list[str]:
    rows = []
    for venue, all_stats in (summary.get("by_venue") or {}).items():
        s = (all_stats or {}).get("prototype3") or {}
        judged = int(s.get("judged") or 0)
        if judged <= 0:
            continue
        rows.append({
            "venue": venue,
            "judged": judged,
            "hits": int(s.get("hits") or 0),
            "hit_rate": s.get("hit_rate"),
            "roi": s.get("roi"),
            "profit": int(s.get("profit_yen") or 0),
        })
    rows.sort(key=lambda r: (
        -(float(r["roi"]) if r["roi"] is not None else -9999),
        -r["hits"],
        r["venue"],
    ))
    return [
        f"・**{r['venue']}** {r['hits']}/{r['judged']}R（{pct(r['hit_rate'])}） "
        f"回収 {pct(r['roi'])}／{money(r['profit'])}"
        for r in rows[:5]
    ]


def build_message(day: str, summary: dict) -> str:
    s = (summary.get("totals") or {}).get("prototype3") or {}
    delivered = int(s.get("delivered") or 0)
    judged = int(s.get("judged") or 0)
    hits = int(s.get("hits") or 0)
    stake = int(s.get("stake_yen") or 0)
    returned = int(s.get("return_yen") or 0)
    profit = int(s.get("profit_yen") or 0)
    manshu = int(s.get("manshu") or 0)
    torigami = int(s.get("torigami") or 0)
    main_hits = int(s.get("main_hits") or 0)
    cover_hits = int(s.get("cover_hits") or 0)
    venue = venue_lines(summary)

    return "\n".join([
        f"🏆 **新人予想家 ゆうき｜{day[4:6]}/{day[6:8]} 日報**",
        "",
        "📊 **今日の成績**",
        f"配信 **{delivered}R**／結果確定 **{judged}R**",
        f"的中 **{hits}/{judged}R＝{pct(s.get('hit_rate'))}**",
        f"投資 {stake:,}円 → 払戻 {returned:,}円",
        f"**収支 {profit:+,}円／回収率 {pct(s.get('roi'))}**",
        "",
        "🎯 **的中内訳**",
        f"本線的中 **{main_hits}R**／抑え的中 **{cover_hits}R**",
        f"万舟 **{manshu}本**／トリガミ **{torigami}R**",
        "",
        "🏁 **場別TOP**",
        *(venue or ["集計なし"]),
        "",
        "📝 各点100円平買いで集計。試作時代のPT3ロジックをそのまま追跡します。",
    ])


def send(day: str, force: bool = False) -> dict:
    path = SCORE_ROOT / day / "summary.json"
    summary = read_json(path)
    if not isinstance(summary, dict):
        raise FileNotFoundError(path)

    marker = MARKER_ROOT / f"{day}.json"
    if marker.exists() and not force:
        saved = read_json(marker, {})
        if saved.get("sent"):
            return {"day": day, "sent": False, "reason": "already_sent"}

    message = build_message(day, summary)
    post(message)
    MARKER_ROOT.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({
        "day": day,
        "sent": True,
        "sent_at": datetime.now(JST).isoformat(),
        "stream": "prototype3",
        "label": "新人予想家 ゆうき",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"day": day, "sent": True}


def default_day() -> str:
    now = datetime.now(JST)
    if now.hour < 6:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=default_day())
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        post("🏆 **新人予想家 ゆうき｜配信テスト**\n新チャンネルへの接続テスト成功！\n本番予想と日報をここへ届けます🔥")
        print(json.dumps({"test": True, "sent": True}, ensure_ascii=False))
        return

    result = send(args.day, args.force)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
