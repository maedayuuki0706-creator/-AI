#!/usr/bin/env python3
"""Independent, research-only EV results sync.

Only writes to the EV research spreadsheet. Never imports forecast or delivery
logic, never edits the production database, Discord, X, or original forecasts.
Run with --dry-run before enabling --write in a separately scheduled service.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request
from collections import defaultdict

SHEET_ID = "1gXM8oPdzAOZkkNFly4B6jXwezV4eFSw7f7St6s49EdY"
REPO = "maedayuuki0706-creator/-AI"
TIERS = (1.05, 1.2, 1.4, 1.6, 1.8, 2.0)
VALID_KEY = re.compile(r"^\d{8}_\d{2}_\d{2}$")
JST = dt.timezone(dt.timedelta(hours=9))


def num(value, default=None):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def official(key: str):
    if not VALID_KEY.fullmatch(key):
        raise ValueError("bad race key")
    date = key[:8]
    path = f"data/prototype_scoreboard/{date}/official/{key}.json"
    url = f"https://raw.githubusercontent.com/{REPO}/main/{path}"
    headers = {"User-Agent": "yuuki-ev-research-only/1.0"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    # Private repositories may require an authenticated GitHub API client.
    if token:
        url = f"https://api.github.com/repos/{REPO}/contents/{path}"
        headers.update({"Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github.raw+json"})
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as result:
            payload = json.loads(result.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(payload, dict):
        return None
    return payload


def close_out(record, payload):
    if record[15] != "未確定" or not payload:
        return None
    status = payload.get("status")
    refund = payload.get("refund_lanes") or []
    prices = payload.get("payouts") or {}
    if status != "settled" or refund or payload.get("special_per_100") is not None:
        # Any refund/cancellation needs specialized settlement rules. Exclude.
        return None
    if len(prices) != 1:
        return None
    winner, payout = next(iter(prices.items()))
    if not re.fullmatch(r"[1-6]-[1-6]-[1-6]", winner):
        return None
    price = num(payout)
    stake = num(record[12])
    if price is None or price < 0 or stake is None or stake <= 0:
        return None
    hit = winner == record[5]
    returned = round((stake / 100) * price) if hit else 0
    return ["○" if hit else "×", returned, "確定",
            returned - stake, returned / stake, winner]


def load_items(records):
    out = []
    for row in records[1:]:
        row = (row + [""] * 24)[:24]
        if not row[0] or not row[3] or not VALID_KEY.fullmatch(row[19]):
            continue
        if row[15] != "確定":
            continue
        ev, stake, payout = num(row[10]), num(row[12]), num(row[14])
        if ev is None or stake is None or payout is None or stake <= 0:
            continue
        out.append({
            "cohort": row[22], "model": row[3], "key": row[19],
            "day": row[0], "venue": row[1], "ev": ev, "stake": stake,
            "payout": payout, "hit": row[13] == "○",
        })
    return out


def metrics(items):
    if not items:
        return [0, 0, 0, "", 0, "", 0, 0, "", 0, 0, 0]
    seen, winning, investments, returned, records = set(), set(), 0, 0, {}
    for it in items:
        key = it["key"]
        seen.add(key)
        if it["hit"]:
            winning.add(key)
        investments += it["stake"]
        returned += it["payout"]
        day = records.setdefault(key, {"stake": 0, "payout": 0})
        day["stake"] += it["stake"]
        day["payout"] += it["payout"]
    n, hits = len(items), sum(it["hit"] for it in items)
    balance = peak = drawdown = 0
    streak = max_streak = 0
    for key in sorted(records):
        r = records[key]
        balance += r["payout"] - r["stake"]
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
        streak = streak + 1 if r["payout"] == 0 else 0
        max_streak = max(max_streak, streak)
    return [len(seen), n, hits, hits / n, len(winning), len(winning) / len(seen),
            investments, returned, returned / investments,
            returned - investments, max_streak, drawdown]


def summary(items, by_dimensions=False):
    cohorts = sorted({i["cohort"] for i in items if i["cohort"]})
    result = []
    for cohort in cohorts:
        subset = [i for i in items if i["cohort"] == cohort]
        models = sorted({i["model"] for i in subset}) + ["全モデル"]
        groups = {"総計": subset}
        if by_dimensions:
            groups = {}
            for i in subset:
                groups.setdefault(f"場:{i['venue']}", []).append(i)
                groups.setdefault(f"日:{i['day']}", []).append(i)
        for model in models:
            for category, group in sorted(groups.items()):
                model_rows = [x for x in group if model == "全モデル" or x["model"] == model]
                if not model_rows:
                    continue
                for tier in TIERS:
                    qualified = [i for i in model_rows if i["ev"] + 1e-9 >= tier]
                    result.append([cohort, model, category, tier] + metrics(qualified))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write ONLY research spreadsheet")
    args = parser.parse_args()
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise SystemExit("Missing GOOGLE_SERVICE_ACCOUNT_JSON: cannot read dedicated research sheet")
    import gspread
    from google.oauth2.service_account import Credentials
    auth = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    book = gspread.authorize(auth).open_by_key(SHEET_ID)
    detail = book.worksheet("EV買い目ログ")
    data = detail.get_all_values()
    if not data or data[0][3] != "AI/モデル" or data[0][19] != "レースキー":
        raise SystemExit("Research schema mismatch; refusing to write")
    pending = defaultdict(list)
    for rownum, source in enumerate(data[1:], start=2):
        row = (source + [""] * 24)[:24]
        if row[15] == "未確定" and VALID_KEY.fullmatch(row[19]):
            pending[row[19]].append((rownum, row))
    updates = []
    not_found = errors = 0
    for key, entries in sorted(pending.items()):
        try:
            payout = official(key)
        except (OSError, ValueError, json.JSONDecodeError):
            errors += 1
            continue
        if payout is None:
            not_found += 1
            continue
        for rownum, row in entries:
            result = close_out(row, payout)
            if result is None:
                continue
            updates.append({"range": f"N{rownum}:S{rownum}", "values": [result]})
            row[13:19] = [str(x) for x in result]
            data[rownum-1] = row
    rows = load_items(data)
    totals = summary(rows)
    slices = summary(rows, by_dimensions=True)
    report = {
        "state": "write" if args.write else "dry-run",
        "pending_races": len(pending), "settled_ticket_updates": len(updates),
        "official_missing": not_found, "fetch_errors": errors,
        "settled_tickets_in_summary": len(rows),
        "threshold_summary_rows": len(totals),
        "venue_and_day_rows": len(slices),
    }
    if args.write:
        # Dedicated sheet writes only. Do not mutate original forecasts.
        if updates:
            detail.batch_update(updates, value_input_option="RAW")
        for name, table in [("EV閾値比較", totals), ("日別場別AI成績", slices)]:
            tab = book.worksheet(name)
            if tab.row_count < len(table) + 1:
                tab.add_rows(len(table) + 1 - tab.row_count)
            existing_rows = max(len(tab.get_all_values()) - 1, 0)
            payload = table + [[""] * 16 for _ in range(max(0, existing_rows - len(table)))]
            if payload:
                tab.update(range_name=f"A2:P{len(payload)+1}", values=payload, raw=True)
        # Record a timestamp without claiming a separate scheduler is configured.
        runtime = book.worksheet("研究ジョブ稼働")
        now = dt.datetime.now(JST).isoformat(timespec="seconds")
        runtime.update(range_name="A14:B17", values=[
            ["最終結果照合", now], ["今回確定チケット", len(updates)],
            ["公式結果未取得レース", not_found],
            ["研究結果照合方式", "独立・本番予想配信非接続"],
        ], raw=True)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
