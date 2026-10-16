"""Manual, offline runner. No network, Discord, X, GitHub Actions or betting APIs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .scenario_research_v1 import generate, review


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("forecast", "review"))
    parser.add_argument("--input", required=True, help="Local JSON with analysis+meta (forecast) or frozen+result (review)")
    parser.add_argument("--out", required=True, help="New output JSON path; existing files are never replaced")
    args = parser.parse_args()
    incoming = _load(args.input)
    if args.action == "forecast":
        result = generate(incoming["analysis"], incoming["meta"])
    else:
        result = review(incoming["frozen"], incoming["result"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({"status": result["status"], "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
