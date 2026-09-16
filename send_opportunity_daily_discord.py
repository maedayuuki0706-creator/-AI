from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

DAY = os.getenv("REPORT_DAY", "20260916")
REPORT_PATH = Path(f"data/opportunity_report_{DAY}.json")
RESULT_PATH = Path(f"data/official_results/{DAY}.json")
LOG_PATH = Path("data/opportunity_alert_deliveries.jsonl")
MARKER_PATH = Path(f"data/opportunity_daily_discord_{DAY}.json")
WEBHOOK_ENV = "DISCORD_WEBHOOK_MID_ODDS"


def read_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_marker(marker):
    MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKER_PATH.write_text(
        json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def post_discord(message: str):
    url = os.getenv(WEBHOOK_ENV, "").strip()
    if not url:
        raise RuntimeError(f"{WEBHOOK_ENV} is not set")
    payload = json.dumps({"content": message, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8")
    for attempt in range(4):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "boat-ai-daily-report/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                response.read()
            time.sleep(0.8)
            return
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            retry = 2.0
            try:
                body = json.loads(exc.read().decode("utf-8", errors="ignore") or "{}")
                retry = float(body.get("retry_after") or retry)
                if retry > 100:
                    retry /= 1000.0
            except Exception:
                pass
            time.sleep(max(1.0, retry) + 0.5)


def combo_parts(combo):
    parts = str(combo or "").split("-")
    return parts if len(parts) == 3 else []


def latest_rows():
    latest = {}
    for row in read_jsonl(LOG_PATH):
        if str(row.get("day") or "") != DAY:
            continue
        stream = str(row.get("stream") or "")
        if stream not in {"mid_odds", "longshot"}:
            continue
        jcd = str(row.get("jcd") or "").zfill(2)
        try:
            rno = int(row.get("rno") or 0)
        except (TypeError, ValueError):
            continue
        key = (stream, jcd, rno)
        if key not in latest or str(row.get("sent_at") or "") >= str(latest[key].get("sent_at") or ""):
            latest[key] = row
    return latest


def pick_set(row):
    return {
        str(item.get("combination") or "").strip()
        for item in (row.get("picks") or [])
        if isinstance(item, dict) and item.get("combination")
    }


def winner_and_payout(results, jcd, rno):
    result = results.get(f"{jcd}:{rno}") or {}
    if result.get("status") != "settled":
        return None, None
    payouts = result.get("payouts") or {}
    if not payouts:
        return None, None
    winner, payout = next(iter(payouts.items()))
    try:
        payout = int(payout)
    except (TypeError, ValueError):
        payout = 0
    return str(winner), payout


def miss_kind(picks, winner):
    win = combo_parts(winner)
    if not win:
        return None
    parsed = [combo_parts(combo) for combo in picks]
    parsed = [parts for parts in parsed if parts]
    if any(set(parts) == set(win) for parts in parsed):
        return "three"
    if any(parts[:2] == win[:2] for parts in parsed):
        return "top2"
    if any(parts[0] == win[0] for parts in parsed):
        return "head"
    return None


def race_list(values):
    return "・".join(f"{r}R" for r in sorted(values)) if values else "なし"


def main():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    results = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    latest = latest_rows()
    marker = {"day": DAY, "overview": False, "venues": [], "complete": False}
    if MARKER_PATH.exists():
        try:
            saved = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved.get("day") == DAY:
                marker.update(saved)
        except (OSError, ValueError):
            pass
    delivered = set(str(x) for x in marker.get("venues") or [])

    venues = report.get("venues") or {}
    ordered = sorted(venues.items(), key=lambda item: str((item[1] or {}).get("jcd") or "99"))
    total_hits = sum(int(((stats or {}).get("mid_odds") or {}).get("hits") or 0) for _, stats in ordered)
    total_races = 12 * len(ordered)
    rate = (100.0 * total_hits / total_races) if total_races else 0.0

    if not marker.get("overview"):
        ranking = sorted(
            ((name, int(((stats or {}).get("mid_odds") or {}).get("hits") or 0)) for name, stats in ordered),
            key=lambda item: (-item[1], item[0]),
        )
        top = " / ".join(f"{name}{hits}/12" for name, hits in ranking[:5])
        overview = (
            f"🔥 **中穴AI｜{DAY[4:6]}/{DAY[6:8]} 会場別日報**\n"
            f"全体 **{total_hits}/{total_races}R＝{rate:.1f}%**\n"
            f"上位：{top}\n\n"
            "各場ごとに、的中レース・配当・惜しい外れ方まで確認します。\n"
            "穴AIは的中したレースだけ🚨形式で軽く掲載。"
        )
        post_discord(overview)
        marker["overview"] = True
        write_marker(marker)

    details = report.get("details") or []
    long_hits = defaultdict(list)
    for item in details:
        if item.get("stream") != "longshot" or not item.get("hit"):
            continue
        jcd = str(item.get("jcd") or "").zfill(2)
        rno = int(item.get("rno") or 0)
        winner = str(item.get("winner") or "")
        _, payout = winner_and_payout(results, jcd, rno)
        long_hits[jcd].append((rno, winner, payout or 0))

    for venue, stats in ordered:
        jcd = str((stats or {}).get("jcd") or "").zfill(2)
        if jcd in delivered:
            continue
        mid_stats = (stats or {}).get("mid_odds") or {}
        hits = int(mid_stats.get("hits") or 0)
        logged = int(mid_stats.get("logged") or 0)
        hit_rate = 100.0 * hits / 12.0

        hit_rows = []
        hit_rnos = []
        one_head_hits = 0
        non_one_hits = 0
        first_half_hits = 0
        second_half_hits = 0
        payout_values = []
        near = {"three": [], "top2": [], "head": []}

        for rno in range(1, 13):
            row = latest.get(("mid_odds", jcd, rno))
            if not row:
                continue
            picks = pick_set(row)
            winner, payout = winner_and_payout(results, jcd, rno)
            if not winner:
                continue
            if winner in picks:
                hit_rnos.append(rno)
                payout_values.append((payout or 0, rno, winner))
                head = combo_parts(winner)[0]
                if head == "1":
                    one_head_hits += 1
                else:
                    non_one_hits += 1
                if rno <= 6:
                    first_half_hits += 1
                else:
                    second_half_hits += 1
                hit_rows.append(f"🎯 {rno}R　**{winner}**　{(payout or 0):,}円")
            else:
                kind = miss_kind(picks, winner)
                if kind:
                    near[kind].append(rno)

        lines = [
            f"🔥 **中穴AI｜{venue} {DAY[4:6]}/{DAY[6:8]}日報**",
            f"的中 **{hits}/12R＝{hit_rate:.1f}%**　｜検証ログ {logged}/12R",
            "",
            "**🎯 的中レース**",
        ]
        lines += hit_rows or ["的中なし"]

        if payout_values:
            total_payout = sum(value for value, _, _ in payout_values)
            best_payout, best_rno, best_combo = max(payout_values)
            lines += [
                "",
                f"的中配当合計（各100円換算） **{total_payout:,}円**",
                f"最高配当 **{best_rno}R {best_combo}／{best_payout:,}円**",
            ]

        lines += [
            "",
            "**🔎 組み合わせの惜しさ**",
            f"3艇一致・着順違い：{race_list(near['three'])}",
            f"1・2着一致→3着違い：{race_list(near['top2'])}",
            f"頭は一致：{race_list(near['head'])}",
            "",
            "**📊 的中の形**",
            f"1号艇頭 {one_head_hits}R／非1号艇頭 {non_one_hits}R",
            f"前半1〜6R {first_half_hits}R／後半7〜12R {second_half_hits}R",
        ]

        near_total = sum(len(v) for v in near.values())
        if hits >= 6:
            memo = "的中率は高水準。現行条件を軸に、惜しい外れだけ組み合わせ改善候補として確認。"
        elif hits >= 4:
            memo = "まずまず。頭一致・3艇一致の取りこぼしがあれば、点数を増やし過ぎず折り返し候補を検証。"
        elif near_total >= 3:
            memo = "的中数以上に狙いは近い可能性あり。組み合わせの作り方を優先して見直す価値あり。"
        else:
            memo = "今日は中穴条件との噛み合わせ弱め。会場別の頭選択から再確認。"
        lines += ["", f"**📝 メモ**\n{memo}"]

        if long_hits.get(jcd):
            lines += ["", "**💣 穴AI｜的中だけ軽く**"]
            for rno, winner, payout in sorted(long_hits[jcd]):
                lines += [f"{venue} {rno}レース", f"{winner}　🚨{payout:,}円的中🎯🚨"]

        message = "\n".join(lines)
        if len(message) > 1950:
            message = message[:1940] + "\n…"
        post_discord(message)
        delivered.add(jcd)
        marker["venues"] = sorted(delivered)
        write_marker(marker)

    marker["complete"] = len(delivered) == len(ordered)
    write_marker(marker)
    print(json.dumps({"sent_venues": len(delivered), "total_venues": len(ordered), "complete": marker["complete"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
