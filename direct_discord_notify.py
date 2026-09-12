"""Direct BOAT RACE official -> Discord notifier.

This notifier intentionally does not depend on the ChatGPT Site API. It discovers
active venues from the BOAT RACE official site, finds races near post time, reads
official pre-race computer focus as a resilient baseline, and posts directly to
Discord. The local prediction engine remains available for richer normalized data.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = "Boat-AI-Navi/3.0 (+direct-discord-notifier)"
VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def textify(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(?:td|th|tr|li|p|div|h[1-6])>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\u3000", " ")
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n+", "\n", raw)
    return raw.strip()


def official_url(kind: str, day: str, jcd: str | None = None, rno: int | None = None) -> str:
    q = {"hd": day}
    if jcd is not None:
        q["jcd"] = jcd
    if rno is not None:
        q["rno"] = str(rno)
    return f"{BASE}/{kind}?{urllib.parse.urlencode(q)}"


def discover_venues(day: str) -> list[str]:
    raw = fetch(official_url("index", day))
    found = re.findall(r"[?&]jcd=(\d{2})(?:&|&amp;)", raw)
    # Some pages put hd before jcd and some put jcd first; collect every jcd parameter.
    if not found:
        found = re.findall(r"(?:\?|&amp;|&)jcd=(\d{2})", raw)
    return sorted({x for x in found if x in VENUES})


def deadlines(day: str, jcd: str) -> list[str]:
    text = textify(fetch(official_url("racelist", day, jcd, 1)))
    pos = text.find("締切予定時刻")
    if pos < 0:
        return []
    chunk = text[pos:pos + 700]
    times = re.findall(r"(?:[01]?\d|2[0-3]):[0-5]\d", chunk)
    out: list[str] = []
    for t in times:
        h, m = map(int, t.split(":"))
        norm = f"{h:02d}:{m:02d}"
        if norm not in out:
            out.append(norm)
        if len(out) == 12:
            break
    return out


def parse_focus(day: str, jcd: str, rno: int) -> list[str]:
    text = textify(fetch(official_url("pcexpect", day, jcd, rno)))
    start = text.find("予想フォーカス")
    if start < 0:
        return []
    end = text.find("この予想に対する自信度", start)
    block = text[start:end if end > start else start + 1200]
    block = block.replace("＝", "=").replace("－", "-").replace("−", "-")
    picks: list[str] = []
    # Expand A=B-C into A-B-C and B-A-C; keep normal A-B-C as-is.
    for a, op, b, c in re.findall(r"(?<!\d)([1-6])\s*([=-])\s*([1-6])\s*-\s*([1-6])(?!\d)", block):
        if op == "=":
            candidates = [f"{a}-{b}-{c}", f"{b}-{a}-{c}"]
        else:
            candidates = [f"{a}-{b}-{c}"]
        for p in candidates:
            if len(set(p.split("-"))) == 3 and p not in picks:
                picks.append(p)
    # Standalone trifectas that the first regex may miss.
    for a, b, c in re.findall(r"(?<!\d)([1-6])\s*-\s*([1-6])\s*-\s*([1-6])(?!\d)", block):
        p = f"{a}-{b}-{c}"
        if len({a,b,c}) == 3 and p not in picks:
            picks.append(p)
    return picks[:8]


def beforeinfo_available(day: str, jcd: str, rno: int) -> bool:
    try:
        text = textify(fetch(official_url("beforeinfo", day, jcd, rno)))
        return "展示" in text and ("展示タイム" in text or "スタート展示" in text)
    except Exception:
        return False


def send_discord(content: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing")
    payload = json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","User-Agent":UA}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status not in (200, 204):
            raise RuntimeError(f"Discord HTTP {r.status}")


def minutes_until(now: datetime, hhmm: str) -> float:
    h, m = map(int, hhmm.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (target - now).total_seconds() / 60.0


def make_message(day: str, jcd: str, rno: int, deadline: str, picks: list[str], exhibition: bool) -> str:
    venue = VENUES.get(jcd, jcd)
    main = picks[:3]
    cover = picks[3:6]
    lines = [
        "🚤 **競艇AIナビ｜直前予想**",
        f"**{venue} {rno}R**　締切予定 **{deadline}**",
        f"展示反映：{'あり' if exhibition else '未確認'}",
        "",
    ]
    if main:
        lines += ["**本線**", " / ".join(main)]
    if cover:
        lines += ["**押さえ**", " / ".join(cover)]
    if not picks:
        lines += ["予想フォーカスを取得できなかったため、このレースの買い目通知は見送ります。"]
    lines += ["", "※BOAT RACE公式の当日データを直接取得する通知経路です。"]
    return "\n".join(lines)


def run_once(now: datetime | None = None, *, force_test: bool = False) -> int:
    now = now or datetime.now(JST)
    if force_test:
        send_discord(
            "✅ **競艇AIナビ 通知テスト成功**\n"
            f"Discord直送経路は動作しています。\n{now.strftime('%Y-%m-%d %H:%M:%S JST')}"
        )
        print("Discord test sent")
        return 0

    day = now.strftime("%Y%m%d")
    venues = discover_venues(day)
    if not venues:
        print("No active venues found")
        return 0

    sent = 0
    checked = 0
    for jcd in venues:
        try:
            times = deadlines(day, jcd)
        except Exception as e:
            print(f"deadline fetch failed jcd={jcd}: {type(e).__name__}")
            continue
        for idx, t in enumerate(times, 1):
            delta = minutes_until(now, t)
            # 5-minute window: intended to fire once with a */5 GitHub schedule,
            # roughly 10-15 minutes before the deadline when exhibition is usually available.
            if not (10.0 <= delta < 15.0):
                continue
            checked += 1
            try:
                picks = parse_focus(day, jcd, idx)
                exhibition = beforeinfo_available(day, jcd, idx)
                if not picks:
                    print(f"skip {jcd} {idx}R: no picks")
                    continue
                send_discord(make_message(day, jcd, idx, t, picks, exhibition))
                sent += 1
                print(f"sent {VENUES.get(jcd,jcd)} {idx}R {t}")
            except Exception as e:
                print(f"race notify failed {jcd} {idx}R: {type(e).__name__}")
    print(f"completed venues={len(venues)} targets={checked} sent={sent}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true")
    args = p.parse_args()
    try:
        return run_once(force_test=args.test)
    except urllib.error.HTTPError as e:
        print(f"HTTP error: {e.code}")
    except urllib.error.URLError:
        print("Network error")
    except Exception as e:
        print(f"Notifier error: {type(e).__name__}: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
