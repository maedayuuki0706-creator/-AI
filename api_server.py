"""Standalone public web app + prediction API for 競艇AIナビ (stdlib only)."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Boat AI Navi listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
