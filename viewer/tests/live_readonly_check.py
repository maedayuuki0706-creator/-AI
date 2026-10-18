"""One-shot read-only network checks; no web server, credentials or writes upstream."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = "https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/"
OUT = Path(__file__).resolve().parents[1] / "docs/live_checks.json"


def get(url):
    started = time.monotonic()
    try:
        with urlopen(Request(url, headers={"User-Agent": "BoatAiNavi-ReadOnlyQA/1.0"}), timeout=48) as response:
            body = response.read()
            return {"url": url, "status": response.status, "cors": response.headers.get("Access-Control-Allow-Origin"), "bytes": len(body), "seconds": round(time.monotonic() - started, 2), "payload": json.loads(body)}
    except Exception as error:
        return {"url": url, "status": getattr(error, "code", None), "error": str(error), "seconds": round(time.monotonic() - started, 2)}


def main():
    day = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d")
    urls = [
        BASE + "sheet_db/meta.json",
        BASE + "live_status/latest.json",
        BASE + "hiyori/requests/20261018_19_12.json",
        BASE + "prototype12_delivery/predictions/20261018_19_12.json",
        BASE + f"race_cards/{day}.json",
        "https://boat-ai-navi-schedule.onrender.com/schedule.json?date=" + day,
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(get, urls))
    for item in results:
        payload = item.pop("payload", None)
        if not payload:
            item["validation"] = "unavailable"
            continue
        url = item["url"]
        if url.endswith("meta.json"):
            valid = payload.get("source") == "Google Sheets 競艇AI データベース" and payload.get("motor_count", 0) > 0
            item["summary"] = {key: payload.get(key) for key in ("snapshot_at", "motor_count", "player_count")}
        elif "/live_status/" in url:
            valid = payload.get("unit_yen") == 100 and bool(payload.get("streams"))
            item["summary"] = {"day": payload.get("day"), "ai_count": len(payload.get("streams", {})), "generated_at": payload.get("generated_at")}
        elif "/requests/" in url:
            valid = payload.get("day") == "20261018" and str(payload.get("jcd")) == "19" and payload.get("rno") == 12 and len(payload.get("official", {}).get("inputs", [])) == 6
            item["summary"] = {"race_identity_match": valid, "boats": len(payload.get("official", {}).get("inputs", []))}
        elif "/predictions/" in url:
            valid = payload.get("day") == "20261018" and str(payload.get("jcd")) == "19" and payload.get("rno") == 12 and bool(payload.get("models", {}).get("prototype2"))
            item["summary"] = {"race_identity_match": valid, "created_at": payload.get("created_at")}
        else:
            races = payload.get("races", [])
            rows = list(races.values()) if isinstance(races, dict) else races
            valid = str(payload.get("day", "")).replace("-", "") == day and isinstance(rows, list)
            item["summary"] = {"day": payload.get("day"), "races": len(rows), "partial": payload.get("partial"), "complete": payload.get("complete")}
        item["validation"] = "pass" if valid else "fail"
    report = {"checked_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "mode": "GET only; independent QA; no upstream mutation", "checks": results}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(item.get("validation") == "fail" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
