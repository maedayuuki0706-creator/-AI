"""Standalone public web app + prediction API for 競艇AIナビ (stdlib only)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlparse
import urllib.error
import urllib.request

import daily_report as daily
import direct_discord_notify as boat_source
from discord_formation import expand_formation
from prediction_engine_v2 import analyze_race_v2
from x_api_client import post_text as post_to_x, verify_user_context, credentials_configured, XPostRejected
from x_delivery_policy import validate_live_row, weighted_length

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DATA_ROOT = ROOT / "data"

X_SYNC_ALLOWED_SOURCES = {"厳選くん", "厳選中穴", "AI重なり本線", "配当期待本線"}
X_SYNC_RAW_BASE = "https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main"
_X_SYNC_LOCK = threading.Lock()
_X_SYNC_POSTED: dict[str, str] = {}
_X_SYNC_UNCERTAIN: set[str] = set()
_X_RESULT_POSTED: dict[str, str] = {}
_X_RESULT_UNCERTAIN: set[str] = set()


class XArchiveUnavailable(RuntimeError):
    pass


def _raw_text(path: str, ref: str = "main") -> str:
    if ref != "main" and not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("invalid archive commit")
    url = f"{X_SYNC_RAW_BASE.rsplit('/', 1)[0]}/{ref}/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Boat-AI-Navi/x-sync-v1", "Accept": "text/plain"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise XArchiveUnavailable(type(exc).__name__) from exc


def _x_sync_state(day: str, ref: str) -> dict:
    # A failed state read must never be interpreted as permission to repost.
    value = json.loads(_raw_text(f"data/x_post_delivery/{day}.json", ref))
    if not isinstance(value, dict):
        raise ValueError("invalid delivery state")
    return value


def _x_archive_post_row(day: str, jcd: str, rno: int, ref: str) -> dict:
    raw = _raw_text(f"data/x_post_delivery/{day}_posts.jsonl", ref)
    matches = []
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("day") or "") == day
            and str(row.get("jcd") or "").zfill(2) == jcd
            and int(row.get("rno") or 0) == rno
            and str(row.get("source") or "") in X_SYNC_ALLOWED_SOURCES
            and not bool(row.get("resend"))
        ):
            matches.append(row)
    if not matches:
        raise ValueError("eligible archived X post not found")
    return matches[0]


def _x_sync_post_row(day: str, jcd: str, rno: int, ref: str) -> dict:
    row = _x_archive_post_row(day, jcd, rno, ref)
    validate_live_row(row)
    return row


def sync_archived_prediction_to_x(day: str, jcd: str, rno: int, archive_ref: str = "", attempt_id: str = "") -> dict:
    day = str(day or "").strip()
    jcd = str(jcd or "").zfill(2)
    rno = int(rno or 0)
    if not re.fullmatch(r"20\d{6}", day) or not re.fullmatch(r"\d{2}", jcd) or not 1 <= rno <= 12:
        raise ValueError("invalid race key")
    if not re.fullmatch(r"[0-9a-f]{40}", str(archive_ref)) or not re.fullmatch(r"[0-9a-f]{32}", str(attempt_id)):
        raise ValueError("a durable archive commit and attempt are required")
    key = f"{day}:{jcd}:{rno}"

    with _X_SYNC_LOCK:
        state = _x_sync_state(day, archive_ref)
        if key in set(map(str, state.get("x_posted_races") or [])):
            return {"ok": True, "already": True, "key": key, "post_id": str((state.get("x_post_ids") or {}).get(key) or "")}
        if key in _X_SYNC_POSTED:
            return {"ok": True, "already": True, "key": key, "post_id": _X_SYNC_POSTED[key]}
        if key in _X_SYNC_UNCERTAIN:
            raise RuntimeError("previous X delivery outcome is uncertain")
        attempt = (state.get("x_attempts") or {}).get(key) or {}
        if attempt.get("id") != attempt_id or attempt.get("status") != "reserved":
            raise ValueError("delivery attempt is not reserved in the durable outbox")

        row = _x_sync_post_row(day, jcd, rno, archive_ref)
        post = str(row.get("post") or "").strip()
        # Keep the first production rollout conservative: hashtag-free posts
        # are known to pass the account's current X write policy.
        post = "\n".join(line for line in post.splitlines() if not line.lstrip().startswith("#")).strip()
        if not post or weighted_length(post) > 280:
            raise ValueError("archived X post is empty or too long")
        validate_live_row(row)
        _X_SYNC_UNCERTAIN.add(key)
        try:
            post_id = post_to_x(post)
        except XPostRejected as exc:
            if 400 <= exc.status < 500:
                _X_SYNC_UNCERTAIN.discard(key)
            raise
        _X_SYNC_POSTED[key] = post_id
        _X_SYNC_UNCERTAIN.discard(key)
        print(f"X sync post sent: {key} post_id={post_id}", flush=True)
        return {"ok": True, "already": False, "key": key, "post_id": post_id}



def _archived_pick_set(row: dict) -> set[str]:
    """Return exactly the tickets users could see in the X prediction post."""
    visible = set()
    for line in str(row.get("post") or "").splitlines():
        text = line.strip()
        if re.fullmatch(r"[1-6]+-[1-6]+-[1-6]+", text):
            try:
                visible.update(expand_formation(text))
            except ValueError:
                pass
    if visible:
        return visible

    # Legacy fallback for older archives without parseable post text.
    picks = set()
    for value in row.get("picks") or []:
        text = str(value.get("combination") if isinstance(value, dict) else value or "").strip()
        if re.fullmatch(r"[1-6]-[1-6]-[1-6]", text):
            picks.add(text)
        elif re.fullmatch(r"[1-6]+-[1-6]+-[1-6]+", text):
            picks.update(expand_formation(text))
    return picks


def _result_text(row: dict, winner: str, payout: int, hit: bool) -> str:
    venue = str(row.get("venue") or row.get("jcd") or "")
    rno = int(row.get("rno") or 0)
    source = str(row.get("source") or "厳選")
    odds = float(payout) / 100.0
    if hit:
        lines = [
            f"🎯 結果｜{venue} {rno}R",
            f"{winner}　{odds:.1f}倍",
            "",
            f"✅ {source} 的中！",
            "次の無料予想も配信します。",
        ]
    else:
        lines = [
            f"📊 結果｜{venue} {rno}R",
            f"{winner}　{odds:.1f}倍",
            "",
            "❌ 不的中",
            "的中もハズレも結果公開します。",
        ]
    text = "\n".join(lines).strip()
    if weighted_length(text) > 280:
        raise ValueError("X result text is too long")
    return text


def sync_archived_result_to_x(day: str, jcd: str, rno: int, archive_ref: str = "", attempt_id: str = "") -> dict:
    day = str(day or "").strip()
    jcd = str(jcd or "").zfill(2)
    rno = int(rno or 0)
    if not re.fullmatch(r"20\d{6}", day) or not re.fullmatch(r"\d{2}", jcd) or not 1 <= rno <= 12:
        raise ValueError("invalid race key")
    if not re.fullmatch(r"[0-9a-f]{40}", str(archive_ref)) or not re.fullmatch(r"[0-9a-f]{32}", str(attempt_id)):
        raise ValueError("a durable archive commit and result attempt are required")
    key = f"{day}:{jcd}:{rno}"

    with _X_SYNC_LOCK:
        state = _x_sync_state(day, archive_ref)
        if key not in set(map(str, state.get("x_posted_races") or [])):
            raise ValueError("prediction was not posted to X")
        if key in set(map(str, state.get("x_result_races") or [])):
            return {
                "ok": True,
                "already": True,
                "key": key,
                "post_id": str((state.get("x_result_post_ids") or {}).get(key) or ""),
            }
        if key in _X_RESULT_POSTED:
            return {"ok": True, "already": True, "key": key, "post_id": _X_RESULT_POSTED[key]}
        if key in _X_RESULT_UNCERTAIN:
            raise RuntimeError("previous X result delivery outcome is uncertain")

        attempt = (state.get("x_result_attempts") or {}).get(key) or {}
        if attempt.get("id") != attempt_id or attempt.get("status") != "reserved":
            raise ValueError("result delivery attempt is not reserved in the durable outbox")

        original_post_id = str((state.get("x_post_ids") or {}).get(key) or "").strip()
        if not original_post_id.isdigit():
            raise ValueError("original X post id is missing")

        row = _x_archive_post_row(day, jcd, rno, archive_ref)
        result = _load_official_result(day, jcd, rno)
        if result.get("status") != "settled":
            return {
                "ok": False,
                "error": "official result pending",
                "definitely_not_posted": True,
                "retryable": True,
            }
        payouts = result.get("payouts") or {}
        if not payouts:
            return {
                "ok": False,
                "error": "official payout unavailable",
                "definitely_not_posted": True,
                "retryable": True,
            }
        winner, payout = max(((str(combo), int(yen)) for combo, yen in payouts.items()), key=lambda item: item[1])
        hit = winner in _archived_pick_set(row)
        text = _result_text(row, winner, payout, hit)

        _X_RESULT_UNCERTAIN.add(key)
        try:
            post_id = post_to_x(text, reply_to=original_post_id)
        except XPostRejected as exc:
            if 400 <= exc.status < 500:
                _X_RESULT_UNCERTAIN.discard(key)
            raise
        _X_RESULT_POSTED[key] = post_id
        _X_RESULT_UNCERTAIN.discard(key)
        print(f"X result sent: {key} winner={winner} odds={payout / 100:.1f} hit={hit} post_id={post_id}", flush=True)
        return {
            "ok": True,
            "already": False,
            "key": key,
            "post_id": post_id,
            "winner": winner,
            "odds": payout / 100.0,
            "hit": hit,
        }


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
    """Load the settled result from our committed official snapshot first.

    Render can occasionally receive an incomplete/blocked BOAT RACE result page
    even after the repository collector has already confirmed the race. Using
    the committed snapshot keeps X result replies aligned with the same official
    result data used by the scoring pipeline.
    """
    day = str(day or "").strip()
    jcd = str(jcd or "").zfill(2)
    rno = int(rno or 0)
    snapshot_path = (
        f"data/prototype_scoreboard/{day}/official/"
        f"{day}_{jcd}_{rno:02d}.json"
    )
    try:
        snapshot = json.loads(_raw_text(snapshot_path, "main"))
        if isinstance(snapshot, dict) and snapshot.get("status") == "settled" and snapshot.get("payouts"):
            return snapshot
    except Exception:
        pass

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


def maybe_send_x_intro_test() -> None:
    nonce = os.getenv("X_INTRO_TEST_NONCE", "").strip()
    text = os.getenv("X_INTRO_TEST_TEXT", "").strip()
    if not nonce or not text:
        return
    try:
        verified = verify_user_context()
        print(f"X auth verified as {verified}", flush=True)
        posts = [part.strip() for part in text.split("\n---XPOST---\n") if part.strip()]
        for index, post in enumerate(posts, 1):
            if weighted_length(post) > 280:
                raise ValueError(f"X intro post {index} is too long")
            post_id = post_to_x(post)
            print(f"X intro test sent nonce={nonce} index={index}/{len(posts)} post_id={post_id}", flush=True)
    except Exception as exc:
        print(f"X intro test failed nonce={nonce}: {type(exc).__name__}: {exc}", flush=True)


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

        if path == "/api/x-status":
            self.send_json(200, {"ok": True, "delivery_version": 2,
                                 "credentials_configured": credentials_configured(),
                                 "intro_test_enabled": bool(os.getenv("X_INTRO_TEST_NONCE", "").strip()
                                                             and os.getenv("X_INTRO_TEST_TEXT", "").strip()),
                                 "outbox_branch": "x-delivery-state"})
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
        path = parsed.path.rstrip("/") or "/"

        if path in {"/api/x-sync", "/api/x-result"}:
            try:
                payload = body_json(self)
                fn = sync_archived_prediction_to_x if path == "/api/x-sync" else sync_archived_result_to_x
                result = fn(
                    payload.get("day"),
                    payload.get("jcd"),
                    int(payload.get("rno") or 0),
                    str(payload.get("archive_ref") or ""),
                    str(payload.get("attempt_id") or ""),
                )
                status = 200 if result.get("ok") else 409
                self.send_json(status, result)
            except (ValueError, json.JSONDecodeError) as e:
                self.send_json(400, {"ok": False, "error": str(e), "definitely_not_posted": True, "retryable": False})
            except XPostRejected as e:
                print(f"X sync rejected: HTTP {e.status}", flush=True)
                self.send_json(502, {"ok": False, "error": f"X HTTP {e.status}",
                                     "definitely_not_posted": 400 <= e.status < 500,
                                     "retryable": e.status == 429})
            except XArchiveUnavailable:
                self.send_json(502, {"ok": False, "error": "archive temporarily unavailable",
                                     "definitely_not_posted": True, "retryable": True})
            except urllib.error.HTTPError as e:
                self.send_json(502, {"ok": False, "error": f"archive HTTP {e.code}",
                                     "definitely_not_posted": True, "retryable": True})
            except Exception as e:
                print(f"X sync failed: {type(e).__name__}: {e}", flush=True)
                self.send_json(500, {"ok": False, "error": type(e).__name__})
            return

        if path != "/predict":
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
    maybe_send_x_intro_test()
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Boat AI Navi listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
