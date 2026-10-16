"""Bounded research GETs, explicit dated cache, and optional isolated foot fetch."""
from datetime import datetime
from pathlib import Path
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from research.scenario_v2.engine import JST, aware, digest, integer, number, reject_outcomes
from . import parsers

BASE = "https://www.boatrace.jp/owpc/pc/race/"


def identity(meta):
    day = str(meta["day"])
    if len(day) != 8 or not day.isdigit():
        raise ValueError("Need YYYYMMDD")
    datetime.strptime(day, "%Y%m%d")
    jcd, rno = integer(meta["jcd"], 1, 24), integer(meta["rno"], 1, 12)
    return f"{day}_{jcd:02}_{rno:02}"


def url(kind, meta):
    if kind not in {"racelist", "beforeinfo", "raceresult"}:
        raise ValueError("Unsupported research endpoint")
    identity(meta)
    return BASE + kind + "?" + urllib.parse.urlencode({"hd": meta["day"], "jcd": f"{int(meta['jcd']):02}", "rno": int(meta["rno"])})


def page_deadline(raw, rno):
    text = parsers.textify(raw)
    pos = text.find("締切予定時刻")
    if pos < 0:
        raise ValueError("Official deadline missing")
    values = re.findall(r"(?:[01]?\d|2[0-3]):[0-5]\d", text[pos:pos+900])
    if len(values) < 12:
        raise ValueError("Incomplete official deadline table")
    h, m = map(int, values[int(rno)-1].split(":"))
    return f"{h:02}:{m:02}"


class PublicClient:
    def __init__(self, shared_cache=None, clock=None):
        self.shared_cache = Path(shared_cache) if shared_cache else None
        self.clock = clock or (lambda: datetime.now(JST))
        self.last_request = 0.

    def read(self, kind, meta, max_age=60):
        now = aware(self.clock()); key = identity(meta); expected = url(kind, meta)
        if self.shared_cache:
            path = self.shared_cache/key/(kind+".json")
            if path.is_file():
                item = json.loads(path.read_text())
                age = (now-aware(item["fetched_at"])).total_seconds()
                if item.get("url") == expected and item.get("race_id") == key and 0 <= age <= max_age:
                    return {**item, "cache_reused": True}
        delay = 2 - (time.monotonic()-self.last_request)
        if delay > 0: time.sleep(delay)
        self.last_request = time.monotonic()
        req = urllib.request.Request(expected, headers={"User-Agent":"BoatAI-Independent-Research/1.0", "Accept-Language":"ja"})
        with urllib.request.urlopen(req, timeout=6) as response:
            if response.geturl() != expected:
                raise ValueError("Unexpected redirect; do not follow sign-in or another race")
            content = response.read(2_000_001)
        if len(content) > 2_000_000:
            raise ValueError("Response too large")
        return {"race_id":key, "url":expected, "fetched_at":aware(self.clock()).isoformat(),
                "body_sha256":digest(content.decode("utf-8",errors="replace")),
                "html":content.decode("utf-8",errors="replace"), "cache_reused":False}


def optional_foot(meta, boats, clock):
    """Child process has a hard limit; no dispatch-module imports or credentials."""
    process = subprocess.run([sys.executable,"-m","research.capture_v1.foot_child",str(meta["day"]),str(meta["jcd"]),str(meta["rno"])],
                             capture_output=True,text=True,timeout=12,check=True)
    raw = json.loads(process.stdout)
    reject_outcomes(raw)
    expected = {b["lane"]:str(b["racer_id"]) for b in boats}
    rows = raw.get("rows",[])
    if len(rows) != 6 or {integer(b["lane"],1,6) for b in rows} != set(expected):
        raise ValueError("Foot preview needs six unique lanes")
    if any(str(b["racer_id"]) != expected[int(b["lane"])] for b in rows):
        raise ValueError("Foot preview racer mismatch")
    raw["observed_at"] = aware(clock()).isoformat()
    return raw


def database_enrichment(root, boats, meta, observed_at):
    """Read-only DB join. Future snapshots and unknown motor periods stay explicit."""
    if not root:
        return {"status":"not_configured", "missing":["db_snapshot", "motor_period"]}
    root = Path(root); metadata = json.loads((root/"meta.json").read_text())
    if aware(metadata["snapshot_at"]) > aware(observed_at):
        raise ValueError("Future database snapshot")
    players = json.loads((root/"players.json").read_text())
    motors = json.loads((root/"motors.json").read_text())
    matches=[]
    for b in boats:
        player=players.get(str(b["racer_id"])) or {}
        motor=motors.get(f"{int(meta['jcd']):02}:{b.get('motor_number')}") or {}
        period = motor.get("start")
        as_of = str(motor.get("as_of") or "").replace("/", "")
        start = str(period or "").replace("/", "")
        usable = len(as_of)==8 and len(start)==8 and start <= as_of <= str(meta["day"])
        b["db_player_observation"]={k:player[k] for k in ["course_win","avg_st","escape","sashi","makuri","makurisashi"] if k in player}
        b["db_motor_observation"]={"motor_number":b.get("motor_number"),"usage_start":period if usable else None,
                                   "as_of":motor.get("as_of") if usable else None,
                                   "period_verified_against_official":False,
                                   "note":"No foot grades inferred from motor rate; current official period identity is still required"}
        matches.append({"lane":b["lane"],"player_matched":bool(player),"motor_history_dated":bool(usable)})
    return {"status":"read_only", "snapshot_at":metadata["snapshot_at"], "matches":matches,
            "missing":["official motor-period confirmation","prior-day foot trajectory","historical ST distribution"]}
