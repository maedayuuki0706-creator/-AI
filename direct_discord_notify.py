"""Direct BOAT RACE official -> prediction engine -> Discord notifier.

No dependency on the ChatGPT Site API. The scheduled path is:
BOAT RACE official data -> local prediction_engine.py -> Discord webhook.
If structured race parsing fails, official computer focus is used only as a fallback
so notification delivery does not silently stop.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from prediction_engine import analyze_race

JST = ZoneInfo("Asia/Tokyo")
BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = "Boat-AI-Navi/3.1 (+direct-discord-notifier)"
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
    raw = unicodedata.normalize("NFKC", raw)
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
    found = re.findall(r"(?:\?|&amp;|&)jcd=(\d{2})", raw)
    return sorted({x for x in found if x in VENUES})


def deadlines(day: str, jcd: str) -> list[str]:
    text = textify(fetch(official_url("racelist", day, jcd, 1)))
    pos = text.find("締切予定時刻")
    if pos < 0:
        return []
    chunk = text[pos:pos + 900]
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


def parse_racelist_boats(day: str, jcd: str, rno: int) -> list[dict]:
    """Parse the six basic data rows from the official racelist text.

    We intentionally use only stable, visible values: national/local rates, average
    ST, F count and motor rates. Missing advanced data stays neutral in the model.
    """
    text = textify(fetch(official_url("racelist", day, jcd, rno)))
    start = text.find("登録番号/級別")
    if start >= 0:
        text = text[start:]

    row_re = re.compile(
        r"(?m)^([1-6])\s*\n(?:[^\n]*\n){0,4}?(\d{4})\s*/\s*(A1|A2|B1|B2)\b"
    )
    matches = list(row_re.finditer(text))
    # Keep the first clean 1..6 sequence only; later current-form numbers can look similar.
    selected = []
    expected = 1
    for m in matches:
        lane = int(m.group(1))
        if lane == expected:
            selected.append(m)
            expected += 1
            if expected == 7:
                break
    if len(selected) != 6:
        return []

    boats: list[dict] = []
    for i, m in enumerate(selected):
        lane = int(m.group(1))
        end = selected[i + 1].start() if i + 1 < len(selected) else min(len(text), m.start() + 2400)
        chunk = text[m.start():end]
        fl = re.search(r"F\s*(\d+)\s*\nL\s*(\d+)\s*\n", chunk)
        if not fl:
            return []
        tail = chunk[fl.end():]
        vals = re.findall(r"(?<![\d.])(?:\d+\.\d+|\d+)(?![\d.])", tail)
        if len(vals) < 13:
            return []
        try:
            nums = [float(x) for x in vals[:13]]
        except ValueError:
            return []
        avg_st = nums[0]
        boats.append({
            "lane": lane,
            "course": lane,
            "predicted_course": lane,
            "avg_st": avg_st,
            "flying": int(fl.group(1)) > 0,
            "win_rate": nums[1],
            "top2_rate": nums[2],
            "top3_rate": nums[3],
            "local_win_rate": nums[4],
            "local_top2_rate": nums[5],
            "motor_top2_rate": nums[8],
            "motor_top3_rate": nums[9],
        })
    return boats


def engine_picks(day: str, jcd: str, rno: int) -> tuple[list[str], float | None]:
    boats = parse_racelist_boats(day, jcd, rno)
    if len(boats) != 6:
        return [], None
    result = analyze_race({"race": {"venue": VENUES.get(jcd, jcd), "boats": boats}, "boats": boats})
    picks = [row["combination"] for row in result.get("trifecta", [])[:8]]
    return picks, result.get("confidence")


def parse_focus(day: str, jcd: str, rno: int) -> list[str]:
    text = textify(fetch(official_url("pcexpect", day, jcd, rno)))
    start = text.find("予想フォーカス")
    if start < 0:
        return []
    end = text.find("この予想に対する自信度", start)
    block = text[start:end if end > start else start + 1200]
    block = block.replace("=", "=").replace("-", "-")
    picks: list[str] = []
    for a, op, b, c in re.findall(r"(?<!\d)([1-6])\s*([=-])\s*([1-6])\s*-\s*([1-6])(?!\d)", block):
        candidates = [f"{a}-{b}-{c}", f"{b}-{a}-{c}"] if op == "=" else [f"{a}-{b}-{c}"]
        for p in candidates:
            if len(set(p.split("-"))) == 3 and p not in picks:
                picks.append(p)
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


def make_message(jcd: str, rno: int, deadline: str, picks: list[str], exhibition: bool, source: str, confidence: float | None) -> str:
    venue = VENUES.get(jcd, jcd)
    main = picks[:3]
    cover = picks[3:6]
    lines = [
        "🚤 **競艇AIナビ｜直前予想**",
        f"**{venue} {rno}R**　締切予定 **{deadline}**",
        f"展示：{'取得確認' if exhibition else '未確認'} / 予想：{source}",
    ]
    if confidence is not None:
        lines.append(f"モデル信頼度：{round(float(confidence) * 100)}%")
    lines.append("")
    if main:
        lines += ["**本線**", " / ".join(main)]
    if cover:
        lines += ["**押さえ**", " / ".join(cover)]
    lines += ["", "※BOAT RACE公式の当日データを直接取得。サイトAPI障害の影響を受けない通知経路です。"]
    return "\n".join(lines)


def run_once(now: datetime | None = None, *, force_test: bool = False) -> int:
    now = now or datetime.now(JST)
    if force_test:
        send_discord(
            "✅ **競艇AIナビ 通知テスト成功**\n"
            "BOAT RACE公式→予想エンジン→Discord直送ルートへ切り替えました。\n"
            f"{now.strftime('%Y-%m-%d %H:%M:%S JST')}"
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
            # One approximately 5-minute notification window, 10-15 minutes before post.
            if not (10.0 <= delta < 15.0):
                continue
            checked += 1
            try:
                picks, confidence = engine_picks(day, jcd, idx)
                source = "独自AI"
                if not picks:
                    picks = parse_focus(day, jcd, idx)
                    confidence = None
                    source = "公式フォーカス補完"
                if not picks:
                    print(f"skip {jcd} {idx}R: no usable prediction")
                    continue
                exhibition = beforeinfo_available(day, jcd, idx)
                send_discord(make_message(jcd, idx, t, picks, exhibition, source, confidence))
                sent += 1
                print(f"sent {VENUES.get(jcd,jcd)} {idx}R {t} source={source}")
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
