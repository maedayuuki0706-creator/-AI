"""Standalone public web app + prediction API for 競艇AIナビ (stdlib only)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
import urllib.request

import daily_report as daily
import direct_discord_notify as boat_source
from prediction_engine_v2 import analyze_race_v2

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DATA_ROOT = ROOT / "data"


def body_json(handler: BaseHTTPRequestHandler) -> dict:
    try:
        n = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        n = 0
    if n <= 0 or n > 1_000_000:
        return {}
    raw = handler.rfile.read(n)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def read_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                items.append(value)
    except OSError:
        pass
    return items


def _opportunity_picks(row: dict) -> set[str]:
    picks: set[str] = set()
    for item in row.get("picks") or []:
        if not isinstance(item, dict):
            continue
        combo = str(item.get("combination") or "").strip()
        if re.fullmatch(r"[1-6]-[1-6]-[1-6]", combo):
            picks.add(combo)
    return picks


def _load_official_result(day: str, jcd: str, rno: int) -> dict:
    try:
        raw = boat_source.fetch(boat_source.official_url("raceresult", day, jcd, rno))
        return daily.parse_payout(raw)
    except Exception:
        return {"status": "pending", "payouts": {}, "refund_lanes": []}


def build_opportunity_report(day: str) -> dict:
    """Rejudge the independent 中穴AI/穴AI streams against official results."""
    if not re.fullmatch(r"20\d{6}", day):
        raise ValueError("day must be YYYYMMDD")

    rows = read_jsonl(DATA_ROOT / "opportunity_alert_deliveries.jsonl")
    chosen: dict[tuple[str, str, int], dict] = {}
    for row in rows:
        if str(row.get("day") or "") != day:
            continue
        stream = str(row.get("stream") or "")
        if stream not in {"mid_odds", "longshot"}:
            continue
        jcd = str(row.get("jcd") or "").zfill(2)
        try:
            rno = int(row.get("rno") or 0)
        except (TypeError, ValueError):
            continue
        if not re.fullmatch(r"\d{2}", jcd) or not 1 <= rno <= 12:
            continue
        key = (stream, jcd, rno)
        old = chosen.get(key)
        if old is None or str(row.get("sent_at") or "") >= str(old.get("sent_at") or ""):
            chosen[key] = row

    race_keys = sorted({(jcd, rno) for _, jcd, rno in chosen})
    results: dict[tuple[str, int], dict] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {
            pool.submit(_load_official_result, day, jcd, rno): (jcd, rno)
            for jcd, rno in race_keys
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = {"status": "pending", "payouts": {}, "refund_lanes": []}

    by_venue: dict[str, dict] = {}
    totals = {
        "mid_odds": {"hits": 0, "logged": 0, "settled": 0},
        "longshot": {"hits": 0, "logged": 0, "settled": 0},
    }
    details: list[dict] = []

    for (stream, jcd, rno), row in sorted(chosen.items(), key=lambda item: (item[0][1], item[0][2], item[0][0])):
        venue = str(row.get("venue") or boat_source.VENUES.get(jcd) or jcd)
        venue_stats = by_venue.setdefault(venue, {
            "jcd": jcd,
            "mid_odds": {"hits": 0, "logged": 0, "settled": 0},
            "longshot": {"hits": 0, "logged": 0, "settled": 0},
        })
        venue_stats[stream]["logged"] += 1
        totals[stream]["logged"] += 1

        result = results.get((jcd, rno)) or {"status": "pending", "payouts": {}}
        hit = False
        winner = None
        payout = None
        if result.get("status") == "settled":
            venue_stats[stream]["settled"] += 1
            totals[stream]["settled"] += 1
            matches = [(combo, int(yen)) for combo, yen in (result.get("payouts") or {}).items() if combo in _opportunity_picks(row)]
            if matches:
                winner, payout = max(matches, key=lambda item: item[1])
                hit = True
                venue_stats[stream]["hits"] += 1
                totals[stream]["hits"] += 1
        details.append({
            "stream": stream,
            "jcd": jcd,
            "venue": venue,
            "rno": rno,
            "status": result.get("status"),
            "hit": hit,
            "winner": winner,
            "payout_per_100": payout,
            "point_count": int(row.get("point_count") or len(_opportunity_picks(row))),
        })

    return {
        "ok": True,
        "day": day,
        "venues": by_venue,
        "totals": totals,
        "details": details,
    }


def maybe_send_pt3_startup_test() -> None:
    """Send a one-shot promoted PT3 webhook test when explicitly enabled."""
    if os.getenv("PT3_TEST_ON_START", "").strip() != "1":
        return
    url = os.getenv("PT3_DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("PT3 startup test skipped: PT3_DISCORD_WEBHOOK_URL missing", flush=True)
        return
    payload = json.dumps({
        "username": "新人予想家 ゆうき",
        "content": "🏆 **新人予想家 ゆうき｜配信テスト**\nRender本番環境から新チャンネルへの接続テスト成功！\n本番予想＋Discord日報をこのチャンネルへ配信します🔥",
        "allowed_mentions": {"parse": []},
    }, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "boat-ai-yuuki-startup-test/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            print(f"PT3 startup test sent status={response.status}", flush=True)
        try:
            import yuuki_daily_report
            day = yuuki_daily_report.default_day()
            result = yuuki_daily_report.send(day, force=True)
            print(f"PT3 startup daily report sent: {result}", flush=True)
        except Exception as report_exc:
            print(f"PT3 startup daily report failed: {type(report_exc).__name__}: {report_exc}", flush=True)
    except Exception as exc:
        print(f"PT3 startup test failed: {type(exc).__name__}: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "BoatAINavi/2.0"

    def send_bytes(self, status: int, data: bytes, content_type: str, *, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            try:
                data = (WEB_ROOT / "index.html").read_bytes()
            except OSError:
                self.send_bytes(500, b"Web UI unavailable", "text/plain; charset=utf-8")
                return
            self.send_bytes(200, data, "text/html; charset=utf-8")
            return

        if path == "/health":
            self.send_json(200, {
                "ok": True,
                "service": "boat-ai-navi",
                "model": "kyoutei-navi-knowledge-v2",
                "web": True,
            })
            return

        if path == "/api/summary":
            state = read_json(DATA_ROOT / "learning_state.json", {})
            self.send_json(200, {
                "samples": state.get("samples", 0),
                "overall": state.get("overall", {}),
                "by_venue": state.get("by_venue", {}),
                "updated_at": state.get("updated_at"),
            })
            return

        if path == "/api/live-status":
            payload = read_json(DATA_ROOT / "live_status" / "latest.json", {})
            if not payload:
                self.send_json(503, {"ok": False, "error": "live status not generated yet"})
                return
            self.send_json(200, payload)
            return

        if path == "/api/predictions":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", ["20"])[0])
            except ValueError:
                limit = 20
            limit = max(1, min(limit, 100))
            items = read_jsonl(DATA_ROOT / "prediction_log.jsonl")
            items.reverse()
            self.send_json(200, {"items": items[:limit], "count": len(items)})
            return

        if path == "/api/opportunity-report":
            query = parse_qs(parsed.query)
            day = str(query.get("day", [""])[0]).strip()
            try:
                payload = build_opportunity_report(day)
            except ValueError as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
                return
            self.send_json(200, payload)
            return

        self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/predict":
            self.send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            payload = body_json(self)
            result = analyze_race_v2(payload)
            self.send_json(200, {"ok": True, "result": result})
        except (ValueError, json.JSONDecodeError) as e:
            self.send_json(400, {"ok": False, "error": str(e)})
        except Exception as e:
            self.send_json(500, {"ok": False, "error": type(e).__name__})

    def log_message(self, fmt: str, *args) -> None:
        print("web", self.address_string(), fmt % args, flush=True)


def main() -> None:
    maybe_send_pt3_startup_test()
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Boat AI Navi listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
