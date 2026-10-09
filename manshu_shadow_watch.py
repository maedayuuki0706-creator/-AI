"""2026-10-10 JST start: INTERNAL-ONLY manshu condition research.
Isolated from Discord/X and all prediction/delivery scripts.
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
START = "20261010"
VERSION = "manshu-shadow-20261010-v1"

def num(v):
    if v is None or isinstance(v, bool) or v == "":
        return None
    try:
        s = str(v).strip()
        return float("-" + s[1:] if s.upper().startswith("F") else s)
    except (ValueError, TypeError):
        return None

def classify(p, now):
    """Only score six-boat snapshots BEFORE deadline AND BEFORE settlement."""
    now = now.astimezone(JST)
    day = str(p.get("day") or "")
    if day < START or day != now.strftime("%Y%m%d") or p.get("settled"):
        return None
    try:
        cutoff = datetime.strptime(day + " " + str(p["deadline"]), "%Y%m%d %H:%M").replace(tzinfo=JST)
        lead = (cutoff - now).total_seconds() / 60
    except (ValueError, TypeError, KeyError):
        return None
    if not 2 <= lead <= 45:
        return None
    rr = p.get("rows") or []
    try:
        b = {int(r["lane"]): r for r in rr}
    except (KeyError, TypeError, ValueError):
        return None
    if len(rr) != 6 or set(b) != set(range(1, 7)):
        return None
    if any(r.get("finish") is not None or r.get("actual_st") is not None or
           r.get("actual_course") is not None for r in rr):
        return None
    st = {i: num(b[i].get("exhibition_st")) for i in range(1, 7)}
    tm = {i: num(b[i].get("exhibition_time")) for i in range(1, 7)}
    wind, wave = num(b[1].get("wind_m")), num(b[1].get("wave_cm"))
    rank = num(b[1].get("exhibition_rank"))
    if (wind is None or wave is None or rank is None or
            any(v is None for v in st.values()) or
            any(v is None or v <= 0 for v in tm.values())):
        return None
    dip = round(st[1] - min(st[i] for i in (2, 3, 4)), 3)
    gap = round(tm[1] - min(tm[i] for i in (2, 3, 4, 5, 6)), 3)
    r5, r6 = num(b[5].get("exhibition_rank")), num(b[6].get("exhibition_rank"))
    upset = (wind >= 3 or wave >= 3) and (
        gap >= 0.13 or (dip >= 0.06 and (wave >= 3 or rank >= 4)) or
        (rank >= 4 and wind >= 3)
    )
    followers = (wave >= 3 and (wind >= 3 or wave >= 4) and rank <= 3
                 and dip < 0.12 and any(x is not None and x <= 3 for x in (r5, r6)))
    flags = (["イン敗北警戒"] if upset else []) + (["ヒモ荒れ警戒"] if followers else [])
    jcd, rno = str(p.get("jcd") or "").zfill(2), int(p.get("rno") or 0)
    if not jcd.isdigit() or not 1 <= rno <= 12:
        return None
    key = f"{day}_{jcd}_{rno:02d}"
    # Freeze all six pre-race observations for later missed-manshu analysis.
    # No actual position, finish, payout or future odds may enter this section.
    pre_boats = [
        {
            "lane": i,
            "racer_id": str(b[i].get("racer_id") or ""),
            "racer_name": str(b[i].get("name") or ""),
            "class": str(b[i].get("current_class") or ""),
            "motor_number": b[i].get("motor_number"),
            "ex_st": st[i], "ex_time": tm[i],
            "ex_rank": num(b[i].get("exhibition_rank")),
            "ex_st_rank": num(b[i].get("exhibition_st_rank")),
            "ex_course": num(b[i].get("exhibition_course")),
            "tilt": num(b[i].get("tilt")),
            "parts_exchange": b[i].get("parts_exchange"),
            "propeller_exchange": b[i].get("propeller_exchange"),
        }
        for i in range(1, 7)
    ]
    return {
        "key": key, "day": day, "jcd": jcd, "rno": rno,
        "venue": p.get("venue") or jcd, "alert": bool(flags), "types": flags,
        "rule": VERSION, "outcome": None,
        "observed_at": now.isoformat(), "captured_at": p.get("captured_at"),
        "deadline": cutoff.isoformat(), "lead_minutes": round(lead, 1),
        "pre_wind_m": wind, "pre_wave_cm": wave, "pre_lane1_rank": rank,
        "pre_lane5_rank": r5, "pre_lane6_rank": r6,
        "pre_inner_dip_s": dip, "pre_outer_fast_gap_s": gap,
        "pre_boats": pre_boats,
        "sniper_join_key": key,
        "sniper_integration_status": "research_only",
        "data_guard": "six_boats_before_deadline_unsettled"
    }

def adjudicate(entry, settled):
    """Only official 3-ren-tan payout may mark manshu."""
    if entry.get("outcome") is not None:
        return False
    key = f'{entry["jcd"]}:{entry["rno"]}'
    r = settled.get(key) or settled.get(f'{int(entry["jcd"])}:{entry["rno"]}')
    if not isinstance(r, dict) or r.get("status") != "settled":
        return False
    payouts = r.get("payouts") or {}
    valid = [(k, num(v)) for k, v in payouts.items()
             if isinstance(k, str) and len(k.split("-")) == 3]
    valid = [(k, v) for k, v in valid if v is not None and v > 0]
    if len(valid) != 1:
        return False
    pick, amount = valid[0]
    if len(set(pick.split("-"))) != 3 or any(k not in "123456" for k in pick.split("-")):
        return False
    entry["outcome"] = {"trifecta": pick, "payout_per_100": int(amount),
                        "manshu": amount >= 10000, "settled": True,
                        "lane1_won": pick[0] == "1",
                        "lane3_won": pick[0] == "3",
                        "lane5_in_top3": "5" in pick.split("-"),
                        "lane6_in_top3": "6" in pick.split("-"),
                        "source": r.get("source_url")}
    return True

def load(path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}

def summarize(day, entries):
    a = list(entries.values())
    alert = [e for e in a if e["alert"]]
    resolved = lambda xs: [x for x in xs if (x.get("outcome") or {}).get("settled")]
    yes, no = resolved(alert), resolved([e for e in a if not e["alert"]])
    mans = lambda xs: [x for x in xs if x["outcome"]["manshu"]]
    rate = lambda hits, total: round(100 * hits / total, 1) if total else None
    by_type = {}
    for name in ("イン敗北警戒", "ヒモ荒れ警戒"):
        t = [e for e in alert if name in e["types"]]
        tr = resolved(t)
        by_type[name] = {"alert_races": len(t), "resolved_races": len(tr),
                         "manshu_races": len(mans(tr)), "manshu_keys": [e["key"] for e in mans(tr)],
                         "manshu_rate_pct": rate(len(mans(tr)), len(tr))}
    all_resolved = yes + no
    all_manshu = len(mans(yes)) + len(mans(no))
    baseline_rate = rate(all_manshu, len(all_resolved))
    precision = rate(len(mans(yes)), len(yes))
    # A warning is not a successful 3-ren-tan prediction or a winning bet.
    # Every metric uses only pre-race observed records; unknown outcomes stay pending.
    return {
        "day": day, "version": VERSION, "discord_posts": 0, "x_posts": 0,
        "observed_races": len(a), "alert_races": len(alert),
        "alert_rate_pct": rate(len(alert), len(a)),
        "resolved_races": len(all_resolved),
        "observed_baseline_manshu_races": all_manshu,
        "observed_baseline_manshu_rate_pct": baseline_rate,
        "resolved_alert_races": len(yes), "pending_alert_races": len(alert)-len(yes),
        "alert_manshu_races": len(mans(yes)),
        "alert_manshu_keys": [e["key"] for e in mans(yes)],
        "alert_manshu_rate_pct": precision,
        "alert_false_positive_races": len(yes) - len(mans(yes)),
        "alert_capture_rate_pct": rate(len(mans(yes)), all_manshu),
        "alert_lift_vs_observed_baseline": (
            round(precision / baseline_rate, 2)
            if precision is not None and baseline_rate else None
        ),
        "nonalert_resolved_races": len(no), "nonalert_manshu_races": len(mans(no)),
        "missed_manshu_races": len(mans(no)),
        "missed_manshu_keys": [e["key"] for e in mans(no)],
        "missed_manshu_rate_of_all_observed_manshu_pct": rate(len(mans(no)), all_manshu),
        "nonalert_manshu_rate_pct": rate(len(mans(no)), len(no)),
        "target_alert_manshu_rate_pct": 30.0,
        "target_vs_actual_gap_points": round(30.0 - precision, 1) if precision is not None else None,
        "by_type": by_type,
        "note": "Shadow alert evaluates manshu occurrence only, NOT winning picks. Coverage is observed pre-race snapshots; unobserved races excluded. Overlapping types counted once."
    }

def run(source, payouts, out, now, lookback=3):
    today = now.astimezone(JST).strftime("%Y%m%d")
    if today < START:
        return []
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for d in range(lookback + 1):
        day = (now.astimezone(JST) - timedelta(days=d)).strftime("%Y%m%d")
        if day < START:
            continue
        path = out / f"{day}.json"
        old = load(path)
        entries = old.get("entries") or {}
        modified = not path.exists()
        if day == today:
            for file in sorted((source / day).glob("*.json")):
                e = classify(load(file), now)
                if e and e["key"] not in entries:
                    entries[e["key"]] = e
                    modified = True
        results = load(payouts / f"{day}.json")
        for e in entries.values():
            if adjudicate(e, results):
                modified = True
        if modified:
            path.write_text(json.dumps({"day": day, "entries": entries, "version": VERSION},
                                       ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        s = summarize(day, entries)
        summary_path = out / f"summary_{day}.json"
        txt = json.dumps(s, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if not summary_path.exists() or summary_path.read_text(encoding="utf-8") != txt:
            summary_path.write_text(txt, encoding="utf-8")
        # Learning export keeps misses, alerted hits and ordinary negative controls.
        # It is a dataset only; it never edits the sniper/prediction model.
        from manshu_shadow_learning import export_learning
        learning_path = out / f"learning_{day}.json"
        learning_text = json.dumps(
            export_learning(day, entries, official_results=results), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        if not learning_path.exists() or learning_path.read_text(encoding="utf-8") != learning_text:
            learning_path.write_text(learning_text, encoding="utf-8")
        summaries.append(s)
    return summaries

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/exhibition_log"))
    parser.add_argument("--payouts", type=Path, default=Path("data/official_results"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    for s in run(args.source, args.payouts, args.out, datetime.now(JST)):
        print(json.dumps({k: s[k] for k in ("day", "observed_races", "alert_races",
            "resolved_alert_races", "pending_alert_races", "alert_manshu_races")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
