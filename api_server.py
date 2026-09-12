"""Minimal HTTP API for the Boat AI prediction engine (stdlib only)."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prediction_engine_v2 import analyze_race_v2


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


class Handler(BaseHTTPRequestHandler):
    server_version = "BoatAINavi/1.0"

    def send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("", "/health"):
            self.send_json(200, {"ok": True, "service": "boat-ai-prediction", "model": "kyoutei-navi-knowledge-v2"})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/predict":
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
        print("api", self.address_string(), fmt % args, flush=True)


def main() -> None:
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Boat AI API listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
