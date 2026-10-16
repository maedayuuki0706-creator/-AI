"""Manual local JSON runner. No automatic acquisition or external writes."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from .engine import generate, review


def write_once(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.link(temp, path)  # atomic, exclusive publication of complete bytes
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["forecast", "review"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=["live", "replay"], default="live")
    args = parser.parse_args()
    incoming = json.loads(Path(args.input).read_text(encoding="utf-8"))
    record = generate(incoming, mode=args.mode) if args.action == "forecast" else review(incoming["frozen"], incoming["result"])
    write_once(args.out, record)
    print(json.dumps({"status": record["status"], "out": args.out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
