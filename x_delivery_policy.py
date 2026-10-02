"""Shared, fail-closed checks for pre-deadline X prediction delivery."""
from datetime import datetime, timezone, timedelta
import re
import unicodedata

JST = timezone(timedelta(hours=9))
ALLOWED_SOURCES = {"厳選くん", "厳選中穴", "AI重なり本線", "配当期待本線"}
MIN_PUBLISH_LEAD_SECONDS = 10 * 60
SOURCE_SAFETY_LEAD_SECONDS = 11 * 60


def validate_live_row(row: dict, now: datetime | None = None, *, min_lead_seconds: int = MIN_PUBLISH_LEAD_SECONDS) -> None:
    now = now or datetime.now(JST)
    if row.get("source") not in ALLOWED_SOURCES or row.get("resend"):
        raise ValueError("not an eligible selected prediction")
    day = str(row.get("day") or "")
    if day != now.astimezone(JST).strftime("%Y%m%d"):
        raise ValueError("prediction is not for today")
    if not re.fullmatch(r"\d{2}:\d{2}", str(row.get("deadline") or "")):
        raise ValueError("prediction deadline is missing")
    deadline = datetime.strptime(day + " " + row["deadline"], "%Y%m%d %H:%M").replace(tzinfo=JST)
    lead_seconds = (deadline - now).total_seconds()
    if lead_seconds < int(min_lead_seconds):
        raise ValueError("prediction is inside the X ten-minute cutoff")
    sent_at = datetime.fromisoformat(str(row.get("sent_at") or ""))
    if sent_at.tzinfo is None:
        raise ValueError("prediction timestamp must include timezone")
    age = (now - sent_at).total_seconds()
    if not -60 <= age <= 900:
        raise ValueError("prediction is not fresh")


def weighted_length(text: str) -> int:
    """Conservative twitter-text v3 count for our URL-free fixed templates.

    CJK counts twice. Composite emoji may be overcounted, never undercounted.
    These templates intentionally contain no URLs or arbitrary user text.
    Reference: twitter/twitter-text config/v3.json.
    """
    ranges = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
    return sum(1 if any(a <= ord(c) <= b for a, b in ranges) else 2
               for c in unicodedata.normalize("NFC", text))
