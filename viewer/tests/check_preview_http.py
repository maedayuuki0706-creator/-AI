"""Check private static Site routes using a Site-scoped credential via hidden stdin.

Pass an HTTPS origin and the token returned by Sites.get_site, never in argv or a
file. Only GETs that exact origin. Does not follow redirects or run a browser.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from zoneinfo import ZoneInfo


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PageMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ""
        self.robots = ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta" and values.get("name") == "robots":
            self.robots = values.get("content", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def read_input():
    settings = None
    if sys.stdin.isatty():
        import termios
        settings = termios.tcgetattr(sys.stdin.fileno())
        quiet = termios.tcgetattr(sys.stdin.fileno())
        quiet[3] &= ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, quiet)
    try:
        print("Ready for private Site HTTP check JSON on stdin (input is hidden).", flush=True)
        return json.loads(sys.stdin.readline())
    finally:
        if settings is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, settings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    inputs = read_input()
    origin, token = inputs.get("origin", "").rstrip("/"), inputs.get("token", "")
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.netloc or parts.path or parts.query or parts.fragment or not token:
        raise SystemExit("A valid Site origin and Site-scoped token are required.")
    routes = ["/", "/races/", "/race/", "/predictions/", "/motors/", "/racers/",
              "/lab/", "/sources/", "/privacy/", "/lab/six-boat/", "/lab/manshu/", "/lab/method/"]
    assets = ["/assets/app.mjs", "/assets/data.mjs", "/assets/analytics.mjs",
              "/assets/site.css", "/assets/og.png", "/data/public/meta.json",
              "/data/public/stats.json", "/robots.txt", "/sitemap.xml"]

    def check(path):
        item = {"path": path}
        expected_file = args.root / (path.strip("/") + "/index.html" if path.endswith("/") and path != "/" else "index.html" if path == "/" else path.lstrip("/"))
        try:
            request = Request(origin + path, headers={"OAI-Sites-Authorization": "Bearer " + token})
            with build_opener(NoRedirect).open(request, timeout=25) as response:
                body = response.read()
                item.update(status=response.status, bytes=len(body), content_type=response.headers.get("Content-Type", ""))
            expected = expected_file.read_bytes()
            item["content_match"] = hashlib.sha256(body).digest() == hashlib.sha256(expected).digest()
            if path in routes:
                page = PageMetadata()
                page.feed(body.decode("utf-8"))
                item.update(title=page.title, robots=page.robots)
                item["pass"] = item["status"] == 200 and item["content_match"] and bool(page.title) and page.robots == "noindex, nofollow"
            else:
                item["pass"] = item["status"] == 200 and item["content_match"]
        except HTTPError as error:
            item.update(status=error.code, error="HTTP " + str(error.code), **{"pass": False})
        except Exception as error:
            item.update(error=type(error).__name__, **{"pass": False})
        return item

    with ThreadPoolExecutor(max_workers=4) as executor:
        checks = list(executor.map(check, routes + assets))
    report = {"origin": origin, "checked_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
              "mode": "authenticated GET, same Site only, no redirects, no rendering browser",
              "all_passed": all(item["pass"] for item in checks), "checks": checks}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
