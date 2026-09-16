# One-time patcher for selected mid-odds routing.
from pathlib import Path


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"target not found in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


alerts = Path("opportunity_alerts.py")

replace_once(
    alerts,
    '    name = "中穴AI" if kind == "mid" else "穴予想"\n',
    '    name = "中穴予想" if kind == "mid" else "穴予想"\n',
)

replace_once(
    alerts,
    '\n\ndef _send(env_name, content):\n',
    '''\n\ndef _is_selected_mid(payload):\n    picks = payload.get("picks") or []\n    if int(payload.get("score") or 0) < 75:\n        return False\n    if not picks or len(picks) > 12:\n        return False\n    best_ev = 0.0\n    for row in picks:\n        ev = row.get("expected_value")\n        if ev is None:\n            ev = _num(row.get("odds")) * _num(row.get("probability"))\n        best_ev = max(best_ev, _num(ev))\n    return best_ev >= 1.05\n\n\ndef _selected_mid_message(message):\n    return str(message).replace(\n        "🔥 **中穴予想｜",\n        "🚨 **厳選中穴予想｜",\n        1,\n    )\n\n\ndef _send(env_name, content):\n''',
)

old_loop = '''        sent_at = datetime.now(app.base.JST).isoformat()\n        for label, env_name in (\n            ("mid", "DISCORD_WEBHOOK_MID_ODDS"),\n            ("long", "DISCORD_WEBHOOK_LONGSHOT"),\n        ):\n            payload = cached[label]\n            try:\n                _send(env_name, payload["message"])\n                _append_log({\n                    "day": record.get("day"),\n                    "jcd": record.get("jcd"),\n                    "venue": record.get("venue"),\n                    "rno": record.get("rno"),\n                    "deadline": record.get("deadline"),\n                    "sent_at": sent_at,\n                    "stream": "mid_odds" if label == "mid" else "longshot",\n                    "score": payload["score"],\n                    "confidence": payload["confidence"],\n                    "score_breakdown": payload["breakdown"],\n                    "picks": payload["picks"],\n                    "point_count": len(payload["picks"]),\n                    "mode": payload["mode"],\n                    "score_version": payload["score_version"],\n                })\n'''

new_loop = '''        sent_at = datetime.now(app.base.JST).isoformat()\n        for label, env_name in (\n            ("mid", "DISCORD_WEBHOOK_MID_ODDS"),\n            ("long", "DISCORD_WEBHOOK_LONGSHOT"),\n        ):\n            payload = cached[label]\n            selected_mid = label == "mid" and _is_selected_mid(payload)\n            target_env = "DISCORD_WEBHOOK_MID_ODDS_SELECTED" if selected_mid else env_name\n            message = _selected_mid_message(payload["message"]) if selected_mid else payload["message"]\n            try:\n                _send(target_env, message)\n                _append_log({\n                    "day": record.get("day"),\n                    "jcd": record.get("jcd"),\n                    "venue": record.get("venue"),\n                    "rno": record.get("rno"),\n                    "deadline": record.get("deadline"),\n                    "sent_at": sent_at,\n                    "stream": "mid_odds" if label == "mid" else "longshot",\n                    "selected": bool(selected_mid),\n                    "delivery_env": target_env,\n                    "score": payload["score"],\n                    "confidence": payload["confidence"],\n                    "score_breakdown": payload["breakdown"],\n                    "picks": payload["picks"],\n                    "point_count": len(payload["picks"]),\n                    "mode": payload["mode"],\n                    "score_version": payload["score_version"],\n                })\n'''
replace_once(alerts, old_loop, new_loop)

print("selected mid-odds routing patched")
