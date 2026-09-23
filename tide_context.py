"""Venue-aware tide context for live boat-race predictions.

Tide is enabled only for venues where BOAT RACE official venue data says
there is a tidal difference. Seawater/brackish water alone is not enough:
controlled/no-tide pools such as Tokoname, Gamagori and Tsu are excluded.

The module calculates:
- rising / falling tide
- normalized water level (0=low, 1=high)
- estimated tide level when high/low heights are available
- minutes since / until the next turning point
- local tidal range

It is deliberately contextual: the values are logged/mined first rather than
being allowed to make a race selected by themselves.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
import html
import json
import math
from pathlib import Path
import re
import urllib.parse
import urllib.request

PROFILE_PATH = Path("data/venue_tide_profiles.json")
UA = "Boat-AI-Navi/tide-context-v1"
JMA_BASE = "https://www.data.jma.go.jp/kaiyou/db/tide/suisan/suisan.php"
WAKAMATSU_URL = "https://www.wmb.jp/sp/index.php?page=datafile-tide_table"
OMURA_URL = "https://omurakyotei.jp/sio/"


@lru_cache(maxsize=1)
def profiles() -> dict:
    try:
        value = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def venue_profile(jcd: str) -> dict:
    return dict(((profiles().get("venues") or {}).get(str(jcd).zfill(2)) or {}))


def _fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "text/html,*/*"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def _clean(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _cells(row: str) -> list[str]:
    return [
        _clean(cell)
        for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.I | re.S)
    ]


def _as_level(value: str) -> float | None:
    text = str(value or "").replace(",", "").strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(cm|m)?", text, re.I)
    if not m:
        return None
    number = float(m.group(1))
    if (m.group(2) or "").lower() == "m":
        number *= 100.0
    return number


def _event(date_text: str, time_text: str, kind: str, level_cm=None, source=None) -> dict | None:
    try:
        when = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return {
        "time": when,
        "kind": str(kind),
        "level_cm": float(level_cm) if level_cm is not None else None,
        "source": source,
    }


def _jma_url(day: str, station: str) -> str:
    date = datetime.strptime(day, "%Y%m%d")
    start = date - timedelta(days=1)
    end = date + timedelta(days=1)
    query = {
        "stn": station,
        "ys": start.strftime("%Y"),
        "ms": start.strftime("%m"),
        "ds": start.strftime("%d"),
        "ye": end.strftime("%Y"),
        "me": end.strftime("%m"),
        "de": end.strftime("%d"),
        "S_HILO": "on",
    }
    return JMA_BASE + "?" + urllib.parse.urlencode(query)


def parse_jma_events(raw: str) -> list[dict]:
    """Parse JMA high/low table rows.

    JMA rows reserve four high-tide time/height pairs followed by four
    low-tide pairs. Empty positions are represented by '*', so fixed pair
    positions remain stable even when a day has fewer extrema.
    """
    out = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", raw, re.I | re.S):
        cells = _cells(tr)
        date_index = next(
            (i for i, cell in enumerate(cells) if re.search(r"\d{4}/\d{1,2}/\d{1,2}", cell)),
            None,
        )
        if date_index is None:
            continue
        m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", cells[date_index])
        if not m:
            continue
        date_text = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        tail = cells[date_index + 1 :]
        # The first cell after the date is the moon-phase column.
        if tail:
            tail = tail[1:]
        # Pad because JMA has four high pairs and four low pairs.
        tail = (tail + ["*"] * 16)[:16]
        for pair_index in range(8):
            time_text = tail[pair_index * 2].strip()
            level_text = tail[pair_index * 2 + 1].strip()
            if not re.fullmatch(r"\d{1,2}:\d{2}", time_text):
                continue
            level = _as_level(level_text)
            if level is None:
                continue
            kind = "high" if pair_index < 4 else "low"
            item = _event(date_text, time_text, kind, level, "jma")
            if item:
                out.append(item)
    return sorted(out, key=lambda x: x["time"])


def parse_wakamatsu_events(raw: str) -> list[dict]:
    out = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", raw, re.I | re.S):
        cells = _cells(tr)
        date_index = next(
            (i for i, cell in enumerate(cells) if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", cell)),
            None,
        )
        if date_index is None:
            continue
        y, m, d = map(int, cells[date_index].split("/"))
        date_text = f"{y:04d}-{m:02d}-{d:02d}"
        tail = cells[date_index + 1 :]
        # Official table order: low time, low level, high time, high level.
        if len(tail) < 4:
            continue
        for kind, t_idx, l_idx in (("low", 0, 1), ("high", 2, 3)):
            time_text = tail[t_idx]
            if not re.fullmatch(r"\d{1,2}:\d{2}", time_text):
                continue
            level = _as_level(tail[l_idx])
            item = _event(date_text, time_text, kind, level, "wakamatsu_official")
            if item:
                out.append(item)
    return sorted(out, key=lambda x: x["time"])


def parse_omura_events(raw: str, year: int) -> list[dict]:
    out = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", raw, re.I | re.S):
        cells = _cells(tr)
        date_index = next(
            (i for i, cell in enumerate(cells) if re.search(r"\d{1,2}月\d{1,2}日", cell)),
            None,
        )
        if date_index is None:
            continue
        m = re.search(r"(\d{1,2})月(\d{1,2})日", cells[date_index])
        if not m:
            continue
        date_text = f"{year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        times = []
        for cell in cells[date_index + 1 :]:
            if re.fullmatch(r"\d{1,2}:\d{2}", cell):
                times.append(cell)
        # Official Omura table order is low tide then high tide.
        if len(times) >= 1:
            item = _event(date_text, times[0], "low", None, "omura_official")
            if item:
                out.append(item)
        if len(times) >= 2:
            item = _event(date_text, times[1], "high", None, "omura_official")
            if item:
                out.append(item)
    return sorted(out, key=lambda x: x["time"])


def _provider_events(day: str, profile: dict, fetcher=None) -> tuple[list[dict], str | None]:
    fetcher = fetcher or _fetch
    provider = str(profile.get("provider") or "")
    try:
        if provider == "jma":
            station = str(profile.get("station_code") or "")
            if not station:
                return [], None
            url = _jma_url(day, station)
            return parse_jma_events(fetcher(url)), url
        if provider == "wakamatsu_official":
            return parse_wakamatsu_events(fetcher(WAKAMATSU_URL)), WAKAMATSU_URL
        if provider == "omura_official":
            year = int(str(day)[:4])
            return parse_omura_events(fetcher(OMURA_URL), year), OMURA_URL
    except Exception:
        return [], None
    return [], None


def _smooth_fraction(fraction: float) -> float:
    fraction = max(0.0, min(1.0, float(fraction)))
    return (1.0 - math.cos(math.pi * fraction)) / 2.0


def context_from_events(
    day: str,
    hhmm: str,
    events: list[dict],
    *,
    profile: dict | None = None,
    source_url: str | None = None,
) -> dict:
    profile = dict(profile or {})
    try:
        target = datetime.strptime(f"{day} {hhmm}", "%Y%m%d %H:%M")
    except ValueError:
        return {"available": False, "status": "invalid_target"}

    ordered = sorted(
        [
            row for row in events
            if isinstance(row.get("time"), datetime) and row.get("kind") in {"high", "low"}
        ],
        key=lambda row: row["time"],
    )
    previous = max((row for row in ordered if row["time"] <= target), key=lambda r: r["time"], default=None)
    following = min((row for row in ordered if row["time"] > target), key=lambda r: r["time"], default=None)
    if not previous or not following or previous["kind"] == following["kind"]:
        return {
            "available": False,
            "status": "insufficient_extrema",
            "source_url": source_url,
        }

    interval = (following["time"] - previous["time"]).total_seconds()
    elapsed = (target - previous["time"]).total_seconds()
    fraction = max(0.0, min(1.0, elapsed / interval)) if interval > 0 else 0.0
    smooth = _smooth_fraction(fraction)
    phase = "rising" if previous["kind"] == "low" else "falling"

    normalized = smooth if phase == "rising" else 1.0 - smooth
    previous_level = previous.get("level_cm")
    next_level = following.get("level_cm")
    estimated_level = None
    tidal_range = None
    if previous_level is not None and next_level is not None:
        previous_level = float(previous_level)
        next_level = float(next_level)
        estimated_level = previous_level + (next_level - previous_level) * smooth
        tidal_range = abs(next_level - previous_level)

    minutes_from = max(0, round(elapsed / 60))
    minutes_to = max(0, round((following["time"] - target).total_seconds() / 60))
    nearest_kind = previous["kind"] if minutes_from <= minutes_to else following["kind"]
    nearest_minutes = min(minutes_from, minutes_to)

    if normalized <= 0.25:
        level_band = "low"
    elif normalized >= 0.75:
        level_band = "high"
    else:
        level_band = "mid"

    if tidal_range is None:
        range_band = "unknown"
    elif tidal_range >= 150:
        range_band = "large"
    elif tidal_range >= 80:
        range_band = "medium"
    else:
        range_band = "small"

    return {
        "available": True,
        "status": "ok",
        "phase": phase,
        "normalized_level": round(normalized, 4),
        "level_band": level_band,
        "estimated_level_cm": round(estimated_level, 1) if estimated_level is not None else None,
        "tidal_range_cm": round(tidal_range, 1) if tidal_range is not None else None,
        "range_band": range_band,
        "minutes_from_prev_turn": minutes_from,
        "minutes_to_next_turn": minutes_to,
        "near_turn": nearest_minutes <= 90,
        "nearest_turn": nearest_kind,
        "nearest_turn_minutes": nearest_minutes,
        "previous_turn": {
            "kind": previous["kind"],
            "time": previous["time"].strftime("%H:%M"),
            "level_cm": previous.get("level_cm"),
        },
        "next_turn": {
            "kind": following["kind"],
            "time": following["time"].strftime("%H:%M"),
            "level_cm": following.get("level_cm"),
        },
        "provider": profile.get("provider"),
        "station": profile.get("station_name"),
        "venue_weight": profile.get("weight", "normal"),
        "source_url": source_url,
    }


def get_tide_context(day: str, jcd: str, hhmm: str | None, *, fetcher=None) -> dict:
    jcd = str(jcd).zfill(2)
    profile = venue_profile(jcd)
    if not profile:
        return {"applicable": False, "available": False, "status": "unknown_venue"}
    if not bool(profile.get("tide_enabled")):
        return {
            "applicable": False,
            "available": False,
            "status": "excluded_no_tidal_difference",
            "water_type": profile.get("water_type"),
            "reason": profile.get("exclusion_reason"),
        }
    if not hhmm:
        return {
            "applicable": True,
            "available": False,
            "status": "missing_race_time",
            "water_type": profile.get("water_type"),
        }

    events, source_url = _provider_events(day, profile, fetcher=fetcher)
    result = context_from_events(day, hhmm, events, profile=profile, source_url=source_url)
    result.update(
        applicable=True,
        water_type=profile.get("water_type"),
        venue=profile.get("venue"),
    )
    return result


def clear_cache() -> None:
    profiles.cache_clear()
