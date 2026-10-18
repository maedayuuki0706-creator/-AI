"""Stand-alone, read-only official deadline service for the public viewer.

This runs independently of sheet-feed, Discord, X, models and Sheets. No writes.
Only two public routes are enabled. No account credentials are used.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from urllib.parse import parse_qs, urlparse

from sheet_feed_server import JST, schedule_snapshot


def parse_day(requested: str | None) -> str:
    today = datetime.now(JST).date()
    if not requested:
        return today.strftime("%Y%m%d")
    if not re.fullmatch(r"20\d{6}", requested):
        raise ValueError("invalid date")
    try:
        date = datetime.strptime(requested, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("invalid date") from exc
    if abs((date - today).days) > 7:
        raise ValueError("day out of public preview range")
    return requested


class Handler(BaseHTTPRequestHandler):
    server_version = "BoatAINaviSchedule/1.0"

    def send_json(self, status: int, result: dict) -> None:
        data = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        uri = urlparse(self.path)
        if uri.path == "/health":
            self.send_json(200, {"ok": True, "mode": "readonly", "service": "boat-ai-navi-schedule"})
            return
        if uri.path != "/schedule.json":
            self.send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            day = parse_day(parse_qs(uri.query).get("date", [None])[0])
            payload = schedule_snapshot(day)
            self.send_json(200, payload)
        except ValueError as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})
        except Exception:
            # Never expose source scrape details or an invented fallback race.
            self.send_json(503, {"ok": False, "error": "official deadline source unavailable"})

    def log_message(self, *args) -> None:
        return


def main() -> None:
    port = int(os.getenv("PORT", "10000"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
