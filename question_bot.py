import asyncio
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from turn_tactics import turn_tactics_answer

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
QUESTION_CHANNEL_NAME = os.getenv("DISCORD_QUESTION_CHANNEL_NAME", "質問").strip()
QUESTION_CHANNEL_ID = os.getenv("DISCORD_QUESTION_CHANNEL_ID", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
PORT = int(os.getenv("PORT", "10000"))
DISCORD_STARTUP_GRACE_SECONDS = float(os.getenv("DISCORD_STARTUP_GRACE_SECONDS", "20"))
DISCORD_CONNECT_ENABLED = os.getenv("DISCORD_CONNECT_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
DISCORD_PUBLIC_DIAGNOSTIC = os.getenv("DISCORD_PUBLIC_DIAGNOSTIC", "0").strip().lower() in {"1", "true", "yes", "on"}
STARTUP_TEST_MESSAGE = os.getenv("STARTUP_TEST_MESSAGE", "").strip()
RACER_PROFILE_PATH = os.getenv("RACER_PROFILE_PATH", "data/racer_profiles.json").strip()
ENCYCLOPEDIA_PATH = os.getenv("ENCYCLOPEDIA_PATH", "data/boat_encyclopedia.json").strip()
VENUE_TIDE_PATH = os.getenv("VENUE_TIDE_PATH", "data/venue_tide_profiles.json").strip()
VENUE_TACTICAL_PATH = os.getenv("VENUE_TACTICAL_PATH", "data/venue_tactical_priors.json").strip()
LIVE_STATUS_URL = os.getenv(
    "LIVE_STATUS_URL",
    "https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/live_status/latest.json",
).strip()
PREDICTION_CHANNEL_NAMES = {
    x.strip().lower()
    for x in os.getenv(
        "DISCORD_PREDICTION_CHANNEL_NAMES",
        "メイン,本線,中穴,穴,厳選,速報,日和,テスト日和,pt3,予想",
    ).split(",")
    if x.strip()
}

MESSAGE_LINK_RE = re.compile(
    r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild>\d+)/(?P<channel>\d+)/(?P<message>\d+)"
)
FORMATION_RE = re.compile(
    r"(?<!\d)([1-6]+)\s*[-－ー]\s*([1-6]+)\s*[-－ー]\s*([1-6]+)(?!\d)"
)
RACE_RE = re.compile(r"(?<!\d)(1[0-2]|[1-9])\s*[RrＲ](?!\w)")
RACE_JP_RE = re.compile(r"(?<!\d)(1[0-2]|[1-9])\s*レース")
BOAT_RE = re.compile(r"(?<!\d)([1-6])\s*号艇")
COURSE_RE = re.compile(r"(?<!\d)([1-6])\s*コース")
TOBAN_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")

VENUES = [
    "桐生", "戸田", "江戸川", "平和島", "多摩川", "浜名湖", "蒲郡", "常滑",
    "津", "三国", "びわこ", "住之江", "尼崎", "鳴門", "丸亀", "児島",
    "宮島", "徳山", "下関", "若松", "芦屋", "福岡", "唐津", "大村",
]
VENUE_TO_JCD = {
    "桐生": "01", "戸田": "02", "江戸川": "03", "平和島": "04",
    "多摩川": "05", "浜名湖": "06", "蒲郡": "07", "常滑": "08",
    "津": "09", "三国": "10", "びわこ": "11", "住之江": "12",
    "尼崎": "13", "鳴門": "14", "丸亀": "15", "児島": "16",
    "宮島": "17", "徳山": "18", "下関": "19", "若松": "20",
    "芦屋": "21", "福岡": "22", "唐津": "23", "大村": "24",
}

GLOSSARY = {
    "pt3": "PT3は、既存予想を軸に日和データを補助材料として融合する予想系統。現在は点数を絞りつつ、本線と迎えを分けて精度・回収の両立を狙う位置づけです。",
    "中穴くん": "中穴くんは、本命一本ではなく中配当帯まで拾う予想系統。荒れすぎは追わず、展開や展示気配から『届く穴』を狙います。",
    "穴くん": "穴くんは高配当狙いの予想系統。全レース乱発ではなく、荒れる材料が揃ったレースを絞るスナイパー運用が基本です。",
    "厳選くん": "厳選くんは、配信数を減らしてでも信頼度の高いレースだけを抽出する予想系統です。",
    "日和": "日和は既存ロジックとは別視点の予想データ。単独利用より、既存予想の取りこぼし補完や一致確認の材料として使います。",
    "逃げ率": "1コースから1着まで押し切る割合を見る指標です。イン信頼度の土台になります。",
    "逃し率": "1コース艇が逃げ切れなかった割合を見る指標です。相手側の攻めが入る余地を考える材料になります。",
    "逃げ": "逃げは、主に1コース艇がスタートから先に1マークを回り、そのまま先頭を守って1着になる決まり手です。インコースの基本形です。",
    "差し": "差しは、先にターンする艇の内側にできたスペースへ艇を入れて抜く決まり手です。2コース艇などでよく見られます。",
    "差し率": "主に内側の艇が先行艇の内を差して1着を取る傾向を見る指標です。",
    "まくり": "まくりは、外側の艇がスタートで内側より優位に出て、1マークで内艇の外をスピードで包み込んで先頭に立つ決まり手です。",
    "捲り": "まくりは、外側の艇がスタートで内側より優位に出て、1マークで内艇の外をスピードで包み込んで先頭に立つ決まり手です。",
    "まくり差し": "まくり差しは、外から攻める勢いを使いながら、1マークで空いた内側のスペースへ切り込んで抜く決まり手です。",
    "捲り差し": "まくり差しは、外から攻める勢いを使いながら、1マークで空いた内側のスペースへ切り込んで抜く決まり手です。",
    "まくり率": "外側からスピードで内艇を包んで1着を取る傾向を見る指標です。",
    "捲り率": "外側からスピードで内艇を包んで1着を取る傾向を見る指標です。",
    "まくり差し率": "外から攻めつつ、空いた内側へ切り込んで1着を取る傾向を見る指標です。",
    "捲り差し率": "外から攻めつつ、空いた内側へ切り込んで1着を取る傾向を見る指標です。",
    "st": "STはスタートタイミング。数字が小さいほどスタートが速い傾向です。展示STだけでなく選手の普段のSTや進入も合わせて見ます。",
    "展示タイム": "展示タイムは周回展示の直線系タイムの一つ。単純に最速艇だけを買うのではなく、伸び・回り足・選手特性とセットで見ます。",
    "チルト": "チルトはモーターの取り付け角度。一般に上げるほど伸び寄り、下げるほど旋回・出足寄りになりやすいですが、水面や調整で変わります。",
    "前付け": "前付けは外枠艇が本番進入で内側のコースを取りに動くこと。進入が深くなり、スタートや1マークの展開が大きく変わる場合があります。",
    "期待値": "期待値は、的中確率とオッズを合わせて『長期的に見て買う価値があるか』を考える指標です。",
    "迎え": "迎えは本線とは別の展開になった時に拾う補完側の買い目です。点数を増やしすぎないのが重要です。",
    "本線": "本線は、そのレースで最も起こりやすいと判断した中心シナリオの買い目です。",
}

_last_reply_by_user: dict[int, float] = {}
_race_context_by_user: dict[int, tuple[str, int, float]] = {}
_venue_context_by_user: dict[int, tuple[str, float]] = {}
_encyclopedia_context_by_user: dict[int, tuple[str, float]] = {}
_water_context_by_user: dict[int, tuple[str, float]] = {}
_stats_cache: dict[str, tuple[float, object]] = {}
_startup_test_sent = False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps(
            {
                "ok": True,
                "service": "boat-ai-question-bot",
                "discord_token": bool(BOT_TOKEN),
                "openai": bool(OPENAI_API_KEY),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[health] listening on :{PORT}", flush=True)


def message_text(message: discord.Message) -> str:
    parts = [message.content or ""]
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(f"{field.name}: {field.value}")
    return "\n".join(x for x in parts if x).strip()


def formation_count(a: str, b: str, c: str) -> int:
    count = 0
    for x in set(a):
        for y in set(b):
            for z in set(c):
                if len({x, y, z}) == 3:
                    count += 1
    return count


def explain_formation(text: str) -> Optional[str]:
    m = FORMATION_RE.search(text)
    if not m:
        return None
    a, b, c = m.groups()
    count = formation_count(a, b, c)
    return (
        f"`{m.group(0)}` は3連単のフォーメーションです。"
        f"1着候補={','.join(sorted(set(a)))}号艇、"
        f"2着候補={','.join(sorted(set(b)))}号艇、"
        f"3着候補={','.join(sorted(set(c)))}号艇。"
        f"同じ艇が重なる組み合わせを除くと **{count}点** です。"
    )


def glossary_answer(question: str, source: str = "") -> Optional[str]:
    q = question.lower()
    formation = explain_formation(question) or explain_formation(source)
    if formation and any(k in q for k in ["何", "なに", "意味", "点", "これ", "フォーメーション"]):
        return formation
    # 「まくり」より「まくり差し」など、より具体的な長い語を優先する。
    for key in sorted(GLOSSARY, key=len, reverse=True):
        if key.lower() in q:
            return GLOSSARY[key]
    return None


def race_hints(text: str):
    venues = [v for v in VENUES if v in text]
    races = RACE_RE.findall(text)
    if not races:
        races = RACE_JP_RE.findall(text)
    race = f"{races[0]}R" if races else None
    return venues, race


class TableRowsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] | None = None
        self._links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "a":
            self._href = attrs_dict.get("href")
            self._link_text = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._href is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            value = re.sub(r"\s+", " ", html.unescape("".join(self._cell))).strip()
            self._row.append(value)
            self._cell = None
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []
        elif tag == "a" and self._href is not None:
            value = re.sub(r"\s+", " ", html.unescape("".join(self._link_text))).strip()
            self._links.append((self._href, value))
            self._href = None
            self._link_text = []


def _cache_get(key: str, ttl: float = 600.0):
    item = _stats_cache.get(key)
    if not item:
        return None
    saved_at, value = item
    if time.monotonic() - saved_at > ttl:
        _stats_cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value):
    _stats_cache[key] = (time.monotonic(), value)
    return value


def _fetch_html_sync(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; BoatAIQuestionBot/1.0)",
            "Accept-Language": "ja,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _number(text: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group(0)) if m else None


def _integer(text: str) -> Optional[int]:
    value = _number(text)
    return int(value) if value is not None else None


def _row_first_value(rows: list[list[str]], label: str) -> Optional[str]:
    wanted = re.sub(r"\s+", "", label)
    for row in rows:
        if not row:
            continue
        first = re.sub(r"\s+", "", row[0])
        if first == wanted and len(row) >= 2:
            return row[1]
    return None


def fetch_race_entries_sync(day: str, venue: str, rno: int):
    jcd = VENUE_TO_JCD.get(venue)
    if not jcd:
        return None
    cache_key = f"entries:{day}:{jcd}:{rno}"
    cached = _cache_get(cache_key, 300)
    if cached is not None:
        return cached

    url = (
        "https://www.boatrace.jp/owpc/pc/race/racelist"
        f"?rno={rno}&jcd={jcd}&hd={day}"
    )
    page = _fetch_html_sync(url)
    parser = TableRowsParser()
    parser.feed(page)

    racers: list[dict[str, str | int]] = []
    seen: set[str] = set()
    for href, link_text in parser._links:
        m = re.search(r"profile\?toban=(\d{4})", href or "")
        if not m:
            continue
        toban = m.group(1)
        if toban in seen:
            continue
        seen.add(toban)
        name = re.sub(r"\s+", "", link_text)
        racers.append({"boat": len(racers) + 1, "toban": toban, "name": name})
        if len(racers) == 6:
            break

    if len(racers) != 6:
        raise RuntimeError(f"出走表の選手情報を6艇分取得できませんでした（{len(racers)}艇）")
    return _cache_set(cache_key, racers)


def _textify_fragment(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(?:td|th|tr|li|p|div|h[1-6])>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\u3000", " ")
    raw = unicodedata.normalize("NFKC", raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n+", "\n", raw)
    return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def fetch_race_boats_sync(day: str, venue: str, rno: int) -> list[dict]:
    jcd = VENUE_TO_JCD.get(venue)
    if not jcd:
        return []
    cache_key = f"raceboats:{day}:{jcd}:{rno}"
    cached = _cache_get(cache_key, 300)
    if cached is not None:
        return cached

    url = (
        "https://www.boatrace.jp/owpc/pc/race/racelist"
        f"?rno={rno}&jcd={jcd}&hd={day}"
    )
    raw = _fetch_html_sync(url, timeout=10)
    boats = []
    for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", raw, re.I | re.S):
        lane_match = re.search(r"is-boatColor([1-6])", body)
        text = _textify_fragment(body)
        registration = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)\b", text)
        if not lane_match or not registration:
            continue
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.I | re.S)
        if len(cells) < 8:
            continue

        start_text = _textify_fragment(cells[3])
        fl = re.search(r"F\s*(\d+)\s*\nL\s*(\d+)\s*\n", start_text)
        if not fl:
            continue

        vals = [start_text[fl.end():].strip()]
        ok = True
        for cell in cells[4:8]:
            values = _textify_fragment(cell).splitlines()
            if len(values) != 3:
                ok = False
                break
            vals.extend(values)
        if not ok or len(vals) != 13:
            continue
        if any(not re.fullmatch(r"(?:\d+(?:\.\d+)?|[-－―—])", value) for value in vals):
            continue
        nums = [float(value) if re.fullmatch(r"\d+(?:\.\d+)?", value) else None for value in vals]

        lane = int(lane_match.group(1))
        name = re.sub(r"\s+", "", text[registration.end():].strip().split("\n")[0])
        boats.append({
            "boat": lane,
            "toban": registration.group(1),
            "class": registration.group(2),
            "name": name,
            "avg_st": nums[0],
            "f_count": int(fl.group(1)),
            "l_count": int(fl.group(2)),
            "win_rate": nums[1],
            "top2_rate": nums[2],
            "top3_rate": nums[3],
            "local_win_rate": nums[4] if any(x is not None for x in nums[4:7]) else None,
            "local_top2_rate": nums[5] if any(x is not None for x in nums[4:7]) else None,
            "local_top3_rate": nums[6] if any(x is not None for x in nums[4:7]) else None,
            "motor_number": int(nums[7]) if nums[7] is not None else None,
            "motor_top2_rate": nums[8],
            "motor_top3_rate": nums[9],
            "boat_number": int(nums[10]) if nums[10] is not None else None,
            "boat_top2_rate": nums[11],
            "boat_top3_rate": nums[12],
        })

    boats = sorted(boats, key=lambda row: row["boat"])
    if len(boats) != 6 or {row["boat"] for row in boats} != set(range(1, 7)):
        raise RuntimeError("公式出走表の選手データを6艇分取得できませんでした")
    return _cache_set(cache_key, boats)


def load_racer_profiles_sync() -> dict:
    cached = _cache_get("racer_profiles", 300)
    if cached is not None:
        return cached
    with open(RACER_PROFILE_PATH, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        data = {"racers": {}}
    return _cache_set("racer_profiles", data)


def _norm_name(text: str) -> str:
    return re.sub(r"[\s\u3000・･]", "", str(text or "")).replace("選手", "")


def _find_profile_by_question(question: str, data: dict):
    q = _norm_name(question)
    matches = []
    for rid, profile in (data.get("racers") or {}).items():
        name = _norm_name(profile.get("name"))
        if len(name) >= 2 and name in q:
            matches.append((len(name), str(rid), profile))
    if not matches:
        return None
    matches.sort(reverse=True, key=lambda row: row[0])
    return matches[0][1], matches[0][2]


def _pct(num, den) -> Optional[float]:
    try:
        den = float(den)
        if den <= 0:
            return None
        return 100.0 * float(num or 0) / den
    except (TypeError, ValueError):
        return None


def _st_text(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.3f}".lstrip("0")


def _row_summary(row: dict) -> str:
    starts = int(row.get("starts") or 0)
    if starts <= 0:
        return "データなし"
    win = _pct(row.get("wins"), starts)
    top2 = _pct(row.get("top2"), starts)
    top3 = _pct(row.get("top3"), starts)
    return (
        f"{starts}走｜1着 {win:.1f}%｜2連 {top2:.1f}%｜3連 {top3:.1f}%"
        f"｜平均ST {_st_text(row.get('avg_st'))}"
    )


def racer_data_answer_sync(question: str, race_context):
    q = question.lower()
    triggers = [
        "選手データ", "選手情報", "選手成績", "どんな選手", "選手どう",
        "平均st", "得意コース", "決まり手", "選手のデータ", "選手について",
    ]
    data = load_racer_profiles_sync()
    named = _find_profile_by_question(question, data)

    boat_m = BOAT_RE.search(question)
    boat_no = int(boat_m.group(1)) if boat_m else None
    toban_m = TOBAN_RE.search(question)
    direct_toban = toban_m.group(1) if toban_m else None

    # If there is no clear racer-related intent, leave the question to other handlers.
    if not any(t in q for t in triggers) and named is None and direct_toban is None:
        return None

    venue = ""
    rno = 0
    official_boats = []
    if race_context:
        venue, rno = race_context
        day = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d")
        try:
            official_boats = fetch_race_boats_sync(day, venue, rno)
        except Exception:
            official_boats = []

    # "若松8Rの選手データ" -> summarize all six.
    if race_context and boat_no is None and named is None and direct_toban is None:
        if not any(t in q for t in ["選手データ", "選手情報", "選手成績"]):
            return None
        if not official_boats:
            return f"{venue}{rno}Rまでは分かったけど、公式出走表の選手データ取得に失敗しました。"
        lines = [f"👥 **{venue}{rno}R 選手データ**"]
        racers = data.get("racers") or {}
        for boat in official_boats:
            p = racers.get(str(boat["toban"])) or {}
            course = (p.get("courses") or {}).get(str(boat["boat"]), {})
            course_win = _pct(course.get("wins"), course.get("starts"))
            course_piece = f"｜{boat['boat']}C1着 {course_win:.1f}%" if course_win is not None and int(course.get("starts") or 0) >= 3 else ""
            lines.append(
                f"{boat['boat']}号艇 {boat['name']} {boat['class']}｜勝率 {boat['win_rate'] if boat['win_rate'] is not None else '—'}"
                f"｜ST {_st_text(boat['avg_st'])}{course_piece}"
            )
        lines.append("※勝率/STは公式出走表、コース1着率はAI学習DB。")
        return "\n".join(lines)

    profile = None
    toban = None
    official = None

    if race_context and boat_no is not None and official_boats:
        official = official_boats[boat_no - 1]
        toban = str(official["toban"])
        profile = (data.get("racers") or {}).get(toban)
    elif direct_toban:
        toban = direct_toban
        profile = (data.get("racers") or {}).get(toban)
    elif named:
        toban, profile = named

    if not profile and not official:
        if any(t in q for t in triggers):
            return "選手名か「若松8Rの1号艇」みたいに、場・レース・艇番を入れて聞いてください。"
        return None

    name = (official or {}).get("name") or (profile or {}).get("name") or ""
    lines = [f"👤 **{name}（{toban}）**"]

    if official:
        f_mark = f"F{official['f_count']}" if official.get("f_count") is not None else ""
        lines.append(
            f"公式: **{official['class']}｜勝率 {official['win_rate'] if official['win_rate'] is not None else '—'}"
            f"｜2連 {official['top2_rate'] if official['top2_rate'] is not None else '—'}%"
            f"｜3連 {official['top3_rate'] if official['top3_rate'] is not None else '—'}%"
            f"｜平均ST {_st_text(official['avg_st'])}｜{f_mark}**"
        )
        if official.get("local_win_rate") is not None:
            lines.append(
                f"{venue}: 勝率 {official['local_win_rate']:.2f}｜2連 {official['local_top2_rate']:.1f}%"
                + (f"｜3連 {official['local_top3_rate']:.1f}%" if official.get("local_top3_rate") is not None else "")
            )
        if official.get("motor_number") is not None:
            lines.append(
                f"モーター{official['motor_number']}号機｜2連 {official['motor_top2_rate']:.1f}%"
                + (f"｜3連 {official['motor_top3_rate']:.1f}%" if official.get("motor_top3_rate") is not None else "")
            )

    if profile:
        starts = int(profile.get("starts") or 0)
        if starts > 0:
            lines.append(f"AI履歴: {_row_summary(profile)}")
        methods = profile.get("win_methods") or {}
        if methods:
            ordered = ["逃げ", "差し", "まくり", "まくり差し", "抜き", "恵まれ"]
            parts = [f"{m}{int(methods.get(m) or 0)}" for m in ordered if int(methods.get(m) or 0) > 0]
            if parts:
                lines.append("決まり手: " + " / ".join(parts))

        if race_context and boat_no is not None:
            course_row = (profile.get("courses") or {}).get(str(boat_no), {})
            if int(course_row.get("starts") or 0) > 0:
                lines.append(f"{boat_no}コース履歴: {_row_summary(course_row)}")
            jcd = VENUE_TO_JCD.get(venue)
            venue_row = (profile.get("venues") or {}).get(str(jcd), {}) if jcd else {}
            if int(venue_row.get("starts") or 0) > 0:
                lines.append(f"{venue}履歴: {_row_summary(venue_row)}")

        first_seen = str(profile.get("first_seen") or "")
        last_seen = str(profile.get("last_seen") or "")
        if len(first_seen) == 8 and len(last_seen) == 8:
            lines.append(
                f"※AI履歴の集計範囲: {first_seen[:4]}/{first_seen[4:6]}/{first_seen[6:]}〜"
                f"{last_seen[:4]}/{last_seen[4:6]}/{last_seen[6:]}"
            )
    return "\n".join(lines)


async def maybe_answer_racer_data(question: str, source: str, user_id: int):
    context = resolve_race_context(user_id, question, source)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(racer_data_answer_sync, question, context),
            timeout=12,
        )
    except asyncio.TimeoutError:
        return "選手データの取得に時間がかかったので一度止めました。少し時間を置いてもう一度聞いてください。"
    except Exception as e:
        print(f"[racer-data] {type(e).__name__}: {e}", flush=True)
        return None


def fetch_racer_course_stats_sync(toban: str, course: int):
    cache_key = f"course:{toban}:{course}"
    cached = _cache_get(cache_key, 900)
    if cached is not None:
        return cached

    urls = [
        f"https://www.boatfrontier.jp/racer/{toban}/course/{course}",
        f"https://boatfrontier.jp/racer/{toban}/course/{course}",
    ]
    last_error = None
    for url in urls:
        try:
            page = _fetch_html_sync(url)
            parser = TableRowsParser()
            parser.feed(page)
            rows = parser.rows

            starts = _integer(_row_first_value(rows, "出走数") or "")
            firsts = _integer(_row_first_value(rows, "1着") or "")
            first_rate = _number(_row_first_value(rows, "1着率") or "")
            second_rate = _number(_row_first_value(rows, "2連対率") or "")
            third_rate = _number(_row_first_value(rows, "3連対率") or "")
            counts = {
                "逃げ": _integer(_row_first_value(rows, "逃げ") or ""),
                "差し": _integer(_row_first_value(rows, "差し") or ""),
                "まくり": _integer(_row_first_value(rows, "まくり") or ""),
                "まくり差し": _integer(_row_first_value(rows, "まくり差し") or ""),
                "抜き": _integer(_row_first_value(rows, "抜き") or ""),
                "恵まれ": _integer(_row_first_value(rows, "恵まれ") or ""),
            }
            if starts is None or first_rate is None:
                raise RuntimeError("コース別成績テーブルを解析できませんでした")
            result = {
                "starts": starts,
                "firsts": firsts,
                "first_rate": first_rate,
                "second_rate": second_rate,
                "third_rate": third_rate,
                "counts": counts,
                "source_url": url,
                "period": "直近12カ月",
            }
            return _cache_set(cache_key, result)
        except Exception as e:
            last_error = e
    raise RuntimeError(str(last_error or "コース別成績を取得できませんでした"))



def fetch_race_result_sync(day: str, venue: str, rno: int) -> dict:
    jcd = VENUE_TO_JCD.get(venue)
    if not jcd:
        raise RuntimeError("場コードが見つかりません")
    cache_key = f"result:{day}:{jcd}:{rno}"
    cached = _cache_get(cache_key, 60)
    if cached is not None:
        return cached

    url = (
        "https://www.boatrace.jp/owpc/pc/race/raceresult"
        f"?rno={rno}&jcd={jcd}&hd={day}"
    )
    raw = _fetch_html_sync(url, timeout=10)
    finish = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", raw, re.S | re.I):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) != 4 or not re.search(r"is-boatColor[1-6]", row):
            continue
        position = _textify_fragment(cells[0])
        lane = _textify_fragment(cells[1])
        racer = _textify_fragment(cells[2])
        m = re.match(r"(\d{4})\s+(.+)", racer)
        if not m or lane not in "123456" or len(lane) != 1:
            continue
        finish.append({
            "position": int(position) if position in list("123456") else None,
            "status": "finished" if position in list("123456") else position,
            "lane": int(lane),
            "toban": m.group(1),
            "name": m.group(2).replace(" ", ""),
        })

    text = _textify_fragment(raw)
    method_m = re.search(r"決まり手\s+(逃げ|差し|まくり差し|まくり|抜き|恵まれ)", text)
    payout_m = re.search(
        r"3連単\s+([1-6])\s*-\s*([1-6])\s*-\s*([1-6])\s+[¥￥]([\d,]+)",
        text,
    )
    if not payout_m:
        return _cache_set(cache_key, {
            "status": "pending",
            "venue": venue,
            "rno": rno,
            "url": url,
        })

    result = {
        "status": "settled",
        "venue": venue,
        "rno": rno,
        "finish": sorted(
            [row for row in finish if isinstance(row.get("position"), int)],
            key=lambda row: row["position"],
        ),
        "trifecta": "-".join(payout_m.group(i) for i in (1, 2, 3)),
        "payout": int(payout_m.group(4).replace(",", "")),
        "method": method_m.group(1) if method_m else None,
        "url": url,
    }
    return _cache_set(cache_key, result)


def race_result_answer_sync(question: str) -> Optional[str]:
    if "結果" not in question and "着順" not in question and "払戻" not in question and "払い戻し" not in question:
        return None
    context = _race_context_from_text(question)
    if context is None:
        return None
    venue, rno = context
    day = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d")
    result = fetch_race_result_sync(day, venue, rno)
    if result.get("status") != "settled":
        return f"🏁 **{venue}{rno}R** は、公式結果がまだ確定していないか取得待ちです。"

    lines = [f"🏁 **{venue}{rno}R 結果**"]
    for row in (result.get("finish") or [])[:3]:
        lines.append(f"{row['position']}着 {row['lane']}号艇 {row['name']}")
    lines.append(
        f"3連単 **{result['trifecta']}**｜**{result['payout']:,}円**"
    )
    if result.get("method"):
        lines.append(f"決まり手: **{result['method']}**")
    lines.append("※BOAT RACE公式の当日結果を参照。")
    return "\n".join(lines)


async def maybe_answer_race_result(question: str) -> Optional[str]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(race_result_answer_sync, question),
            timeout=12,
        )
    except asyncio.TimeoutError:
        return "公式結果の取得に時間がかかったので一度止めました。少し時間を置いてもう一度聞いてください。"
    except Exception as e:
        print(f"[race-result] {type(e).__name__}: {e}", flush=True)
        return None


def fetch_national_course_first_rate_sync(course: int) -> Optional[float]:
    cache_key = f"national:first:{course}"
    cached = _cache_get(cache_key, 3600)
    if cached is not None:
        return cached
    try:
        page = _fetch_html_sync("https://kyotei-japan.com/course.html")
        parser = TableRowsParser()
        parser.feed(page)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
        patterns = [
            rf"{course}\s*コース\s*1着率\s*(\d+(?:\.\d+)?)\s*%",
            rf"{course}コース.{0,80}?1着率.{0,40}?(\d+(?:\.\d+)?)\s*%",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.S)
            if m:
                return _cache_set(cache_key, float(m.group(1)))
    except Exception:
        pass
    return None


def requested_stats_metric(question: str) -> Optional[str]:
    q = question.replace("捲り差し", "まくり差し").replace("捲り", "まくり")
    aliases = [
        ("まくり差し率", ["まくり差し率"]),
        ("まくり率", ["まくり率"]),
        ("差し率", ["差し率"]),
        ("逃げ率", ["逃げ率"]),
        ("3連対率", ["3連対率", "3連率"]),
        ("2連対率", ["2連対率", "2連率"]),
        ("1着率", ["1着率", "一着率"]),
        ("出走数", ["出走数", "何走"]),
    ]
    for metric, words in aliases:
        if any(word in q for word in words):
            return metric
    return None


def _race_context_from_text(text: str):
    venues, race = race_hints(text)
    if not venues or not race:
        return None
    return venues[0], int(race[:-1])


def resolve_race_context(user_id: int, question: str, source: str = ""):
    context = _race_context_from_text(question)
    if context is None and source:
        context = _race_context_from_text(source)
    if context is not None:
        _race_context_by_user[user_id] = (context[0], context[1], time.monotonic())
        return context

    previous = _race_context_by_user.get(user_id)
    if previous and time.monotonic() - previous[2] <= 1800:
        return previous[0], previous[1]
    return None


def course_stats_answer_sync(question: str, race_context):
    metric = requested_stats_metric(question)
    if not metric:
        return None

    boat_m = BOAT_RE.search(question)
    course_m = COURSE_RE.search(question)
    boat_no = int(boat_m.group(1)) if boat_m else None
    stat_course = int(course_m.group(1)) if course_m else None

    toban_m = TOBAN_RE.search(question)
    toban = toban_m.group(1) if toban_m else None
    racer_name = ""

    if race_context:
        venue, rno = race_context
        if boat_no is None and stat_course is not None:
            boat_no = stat_course
        if boat_no is not None:
            day = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d")
            entries = fetch_race_entries_sync(day, venue, rno)
            racer = entries[boat_no - 1]
            toban = str(racer["toban"])
            racer_name = str(racer["name"])
        if stat_course is None and boat_no is not None:
            stat_course = boat_no
    else:
        venue = ""
        rno = 0

    if stat_course is None:
        return None

    if toban is None:
        venue_only = _venue_from_question(question)
        if venue_only:
            profile = _official_venue_features_sync(venue_only)
            course_row = ((profile.get("courses") or {}).get(str(stat_course)) or {})
            period = profile.get("period") or "直近3か月"
            if course_row:
                if metric == "1着率" and course_row.get("win_pct") is not None:
                    return (
                        f"{venue_only}の**{stat_course}コース1着率は{float(course_row['win_pct']):.1f}%**です。"
                        f" 集計は{period}。"
                    )
                if metric == "2連対率" and course_row.get("top2_pct") is not None:
                    return (
                        f"{venue_only}の**{stat_course}コース2連対率は{float(course_row['top2_pct']):.1f}%**です。"
                        f" 集計は{period}。"
                    )
                if metric == "3連対率" and course_row.get("top3_pct") is not None:
                    return (
                        f"{venue_only}の**{stat_course}コース3連対率は{float(course_row['top3_pct']):.1f}%**です。"
                        f" 集計は{period}。"
                    )
                if metric in ("逃げ率", "差し率", "まくり率", "まくり差し率"):
                    method = metric[:-1]
                    value = (course_row.get("methods") or {}).get(method)
                    if value is not None:
                        return (
                            f"{venue_only}の直近データでは、**{stat_course}コースの{method}構成比は"
                            f"{float(value):.1f}%**です。集計は{period}。"
                        )
        if metric == "1着率":
            rate = fetch_national_course_first_rate_sync(stat_course)
            if rate is not None:
                return (
                    f"全国集計では、**{stat_course}コースの1着率は約{rate:.1f}%**です。"
                    " レースや選手を指定すると、その選手のコース別成績まで見にいけます。"
                )
        return None

    stats = fetch_racer_course_stats_sync(toban, stat_course)
    prefix = ""
    if race_context and boat_no is not None:
        prefix = f"{venue}{rno}Rの{boat_no}号艇・{racer_name}（{toban}）"
    elif racer_name:
        prefix = f"{racer_name}（{toban}）"
    else:
        prefix = f"登録番号{toban}"

    if metric == "1着率":
        detail = f"**{stats['first_rate']:.1f}%**"
        if stats["starts"] is not None and stats["firsts"] is not None:
            detail += f"（{stats['starts']}走・1着{stats['firsts']}回）"
        return (
            f"{prefix}の、**{stat_course}コース進入時の1着率は{detail}**です。"
            f" 集計は{stats['period']}。実際の進入が変わった場合は、そのコース側の数字を見るのが大事です。"
        )

    if metric in ("2連対率", "3連対率"):
        key = "second_rate" if metric == "2連対率" else "third_rate"
        value = stats.get(key)
        if value is None:
            return None
        return (
            f"{prefix}の、**{stat_course}コース進入時の{metric}は{value:.1f}%**です。"
            f" 集計は{stats['period']}です。"
        )

    if metric == "出走数":
        return (
            f"{prefix}は、{stats['period']}で**{stat_course}コースから{stats['starts']}走**しています。"
        )

    if metric in ("逃げ率", "差し率", "まくり率", "まくり差し率"):
        method = metric[:-1]
        count = stats["counts"].get(method)
        starts = stats["starts"]
        if count is None or not starts:
            return None
        rate = count / starts * 100.0
        return (
            f"{prefix}の、{stats['period']}の**{stat_course}コースでの{method}は"
            f"{count}回／{starts}走（約{rate:.1f}%）**です。"
        )

    return None


async def maybe_answer_course_stats(question: str, source: str, user_id: int):
    metric = requested_stats_metric(question)
    if not metric:
        return None
    context = resolve_race_context(user_id, question, source)
    try:
        return await asyncio.to_thread(course_stats_answer_sync, question, context)
    except Exception as e:
        print(f"[stats] {type(e).__name__}: {e}", flush=True)
        if context:
            venue, rno = context
            return (
                f"{venue}{rno}Rまでは特定できたけど、コース別の数値取得に失敗しました。"
                " 少し時間を置いてもう一度聞いてください。"
            )
        return None


async def fetch_linked_message(message: discord.Message) -> Optional[discord.Message]:
    m = MESSAGE_LINK_RE.search(message.content or "")
    if not m:
        return None
    if not message.guild or str(message.guild.id) != m.group("guild"):
        return None
    channel = message.guild.get_channel(int(m.group("channel")))
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return None
    try:
        return await channel.fetch_message(int(m.group("message")))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def get_reference_message(message: discord.Message) -> Optional[discord.Message]:
    ref = message.reference
    if ref:
        if isinstance(ref.resolved, discord.Message):
            return ref.resolved
        if ref.message_id:
            try:
                return await message.channel.fetch_message(ref.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
    return await fetch_linked_message(message)


def is_prediction_channel(channel) -> bool:
    name = getattr(channel, "name", "").lower()
    return any(key in name for key in PREDICTION_CHANNEL_NAMES)


async def find_recent_prediction(message: discord.Message) -> Optional[discord.Message]:
    if not message.guild:
        return None
    venues, race = race_hints(message.content or "")
    if not venues and not race:
        return None
    best: Optional[discord.Message] = None
    for channel in message.guild.text_channels:
        if not is_prediction_channel(channel):
            continue
        perms = channel.permissions_for(message.guild.me)
        if not (perms.view_channel and perms.read_message_history):
            continue
        try:
            async for candidate in channel.history(limit=40):
                text = message_text(candidate)
                if venues and not any(v in text for v in venues):
                    continue
                if race and race.lower() not in text.lower().replace(" ", ""):
                    continue
                if best is None or candidate.created_at > best.created_at:
                    best = candidate
                break
        except (discord.Forbidden, discord.HTTPException):
            continue
    return best



LIVE_STATUS_STREAMS = ["main", "mid_odds", "selected", "hiyori", "prototype3", "longshot"]
STREAM_ALIASES = {
    "メイン": "main",
    "本線": "main",
    "中穴": "mid_odds",
    "中穴くん": "mid_odds",
    "厳選": "selected",
    "厳選くん": "selected",
    "日和": "hiyori",
    "pt3": "prototype3",
    "PT3": "prototype3",
    "穴": "longshot",
    "穴くん": "longshot",
    "pt1": "prototype1",
    "PT1": "prototype1",
    "pt2": "prototype2",
    "PT2": "prototype2",
}


def fetch_json_sync(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "boat-ai-question-bot/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmt_pct(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}%"


def _venue_from_question(question: str) -> Optional[str]:
    for venue in VENUES:
        if venue in question:
            return venue
    return None


def _requested_stream(question: str) -> Optional[str]:
    q = question.lower()
    # Longer aliases first so "中穴くん" wins over "中穴".
    for alias, key in sorted(STREAM_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if alias.lower() in q:
            return key
    return None


def live_venue_answer_sync(question: str) -> Optional[str]:
    q = question.lower()
    venue = _venue_from_question(question)
    if not venue:
        return None
    # Race-specific "結果" belongs to the official race-result handler.
    if _race_context_from_text(question) is not None and any(k in q for k in ["結果", "着順", "払戻", "払い戻し"]):
        return None
    if not any(k in q for k in ["的中率", "回収率", "roi", "成績", "調子", "今どう", "現状", "結果"]):
        return None

    data = fetch_json_sync(LIVE_STATUS_URL)
    venue_data = (data.get("venues") or {}).get(venue)
    if not venue_data:
        return f"{venue}は、いまの集計データではまだ成績を確認できません。"

    generated_at = str(data.get("generated_at") or "")
    time_label = ""
    m = re.search(r"T(\d{2}:\d{2})", generated_at)
    if m:
        time_label = f"（{m.group(1)}更新）"

    requested = _requested_stream(question)
    if requested:
        stat = venue_data.get(requested)
        if not stat or not stat.get("judged"):
            label = (stat or {}).get("label") or requested
            return f"{venue}の{label}は、{time_label or '現在'} 判定済みデータがまだありません。"
        return (
            f"📍{venue} {stat.get('label', requested)} {time_label}\n"
            f"的中 **{stat.get('hits', 0)}/{stat.get('judged', 0)} = {_fmt_pct(stat.get('hit_rate'))}**\n"
            f"回収率 **{_fmt_pct(stat.get('roi'))}**"
            + (f"｜万舟 {stat.get('manshu', 0)}本" if stat.get("manshu") is not None else "")
        )

    lines = [f"📍{venue} 現在の成績 {time_label}".rstrip()]
    for key in LIVE_STATUS_STREAMS:
        stat = venue_data.get(key)
        if not stat:
            continue
        label = stat.get("label", key)
        judged = int(stat.get("judged") or 0)
        if judged <= 0:
            if key == "longshot":
                lines.append(f"・{label}: 配信/判定なし")
            continue
        lines.append(
            f"・{label}: **{stat.get('hits', 0)}/{judged} "
            f"({_fmt_pct(stat.get('hit_rate'))})**｜回収 {_fmt_pct(stat.get('roi'))}"
        )
    lines.append("※判定済みレースだけで集計。結果待ちは分母に入れていません。")
    return "\n".join(lines)


async def live_venue_answer(question: str) -> Optional[str]:
    try:
        return await asyncio.to_thread(live_venue_answer_sync, question)
    except Exception as e:
        print(f"[live-status] {type(e).__name__}: {e}", flush=True)
        return None


def _load_json_file_cached(path: str, cache_key: str, ttl: float = 300.0) -> dict:
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached
    try:
        with open(path, "r", encoding="utf-8") as fp:
            value = json.load(fp)
        if not isinstance(value, dict):
            value = {}
    except Exception:
        value = {}
    return _cache_set(cache_key, value)


def _norm_knowledge_text(text: str) -> str:
    return (
        unicodedata.normalize("NFKC", str(text or ""))
        .lower()
        .replace(" ", "")
        .replace("　", "")
    )


def _official_venue_features_sync(venue: str) -> dict:
    """Fetch current BOAT RACE official venue notes and recent course stats."""
    jcd = VENUE_TO_JCD.get(venue)
    if not jcd:
        return {}
    cache_key = f"official_venue:{jcd}"
    cached = _cache_get(cache_key, 3600)
    if cached is not None:
        return cached

    result = {
        "venue": venue,
        "jcd": jcd,
        "race_feature": None,
        "water_feature": None,
        "period": None,
        "courses": {},
        "source_feature": f"https://www.boatrace.jp/owpc/pc/site/place/stadium/br{jcd}/",
        "source_stats": f"https://www.boatrace.jp/owpc/pc/data/stadium?jcd={jcd}",
    }

    try:
        raw = _fetch_html_sync(result["source_feature"], timeout=10)
        lines = _textify_fragment(raw).splitlines()

        def section_after(heading: str, stop_heading: str | None = None) -> Optional[str]:
            try:
                start = next(i for i, line in enumerate(lines) if line.strip() == heading)
            except StopIteration:
                return None
            collected = []
            for line in lines[start + 1 :]:
                value = line.strip()
                if not value:
                    continue
                if stop_heading and value == stop_heading:
                    break
                if "詳細データはこちら" in value:
                    break
                if value.startswith("ボートレース場") and collected:
                    break
                collected.append(value)
                if len(" ".join(collected)) >= 180:
                    break
            text = " ".join(collected).strip()
            return text[:220] if text else None

        result["race_feature"] = section_after("レースの特徴", "水面特性")
        result["water_feature"] = section_after("水面特性")
    except Exception as e:
        print(f"[venue-feature] {venue}: {type(e).__name__}: {e}", flush=True)

    try:
        raw = _fetch_html_sync(result["source_stats"], timeout=10)
        parser = TableRowsParser()
        parser.feed(raw)

        for row in parser.rows:
            if len(row) < 13 or row[0].strip() not in {"1", "2", "3", "4", "5", "6"}:
                continue
            try:
                course = int(row[0].strip())
                placing = [float(str(row[i]).replace("%", "").strip()) for i in range(1, 7)]
                methods = [float(str(row[i]).replace("%", "").strip()) for i in range(7, 13)]
            except (TypeError, ValueError):
                continue
            key = str(course)
            if key in result["courses"]:
                continue
            result["courses"][key] = {
                "win_pct": placing[0],
                "second_pct": placing[1],
                "third_pct": placing[2],
                "top2_pct": round(placing[0] + placing[1], 1),
                "top3_pct": round(placing[0] + placing[1] + placing[2], 1),
                "methods": {
                    "逃げ": methods[0],
                    "まくり": methods[1],
                    "差し": methods[2],
                    "まくり差し": methods[3],
                    "抜き": methods[4],
                    "恵まれ": methods[5],
                },
            }
            if len(result["courses"]) == 6:
                break

        text = _textify_fragment(raw)
        m = re.search(
            r"集計期間\s*[:：]?\s*(\d{4}/\d{1,2}/\d{1,2})\s*[～〜~\-]\s*(\d{4}/\d{1,2}/\d{1,2})",
            text,
        )
        if m:
            result["period"] = f"{m.group(1)}～{m.group(2)}"
    except Exception as e:
        print(f"[venue-stats] {venue}: {type(e).__name__}: {e}", flush=True)

    return _cache_set(cache_key, result)


def _dominant_outer_course(profile: dict) -> tuple[int, float] | None:
    choices = []
    for course in range(2, 7):
        row = (profile.get("courses") or {}).get(str(course)) or {}
        if row.get("win_pct") is not None:
            choices.append((course, float(row["win_pct"])))
    return max(choices, key=lambda item: item[1]) if choices else None


def water_type_concept_answer_sync(question: str, user_id: int) -> Optional[str]:
    """Explain water-type characteristics and contextual follow-ups."""
    q = _norm_knowledge_text(question)
    explicit = next((kind for kind in ("淡水", "海水", "汽水") if kind in q), None)

    if explicit and not _venue_from_question(question):
        _water_context_by_user[user_id] = (explicit, time.monotonic())
        kind = explicit
    else:
        kind = None
        ctx = _water_context_by_user.get(user_id)
        follow_words = [
            "特徴", "違い", "風", "向かい風", "追い風", "波", "うねり",
            "スタート", "st", "ターン", "旋回", "乗り味", "浮力", "モーター",
            "伸び", "出足", "潮", "干満", "狙い目", "影響"
        ]
        if not explicit and len(q) <= 24 and any(word in q for word in follow_words):
            if ctx and time.monotonic() - ctx[1] <= 900:
                kind = ctx[0]

    if not kind:
        return None

    # Leave cross-venue list questions to the dedicated list handler.
    list_words = ["どこ", "どの場", "の場", "一覧", "全部", "何場", "どれ"]
    if explicit and any(word in q for word in list_words):
        return None

    asks_wind = any(word in q for word in ["風", "向かい風", "追い風"])
    asks_start = any(word in q for word in ["スタート", "st"])
    asks_turn = any(word in q for word in ["ターン", "旋回", "乗り味"])
    asks_motor = any(word in q for word in ["モーター", "伸び", "出足"])
    asks_tide = any(word in q for word in ["潮", "干満", "満潮", "干潮"])
    asks_feature = any(word in q for word in ["特徴", "違い", "浮力", "影響"])

    basics = {
        "淡水": (
            "海水より塩分が少なく浮力は小さめ。艇が水に乗る感触や旋回時の掛かり方に差が出ることがある。"
            "水質そのものによる潮汐は基本ないので、予想では風・波・水面形状・選手機力を切り分けて見やすい。"
        ),
        "海水": (
            "淡水より浮力が大きめで、艇の乗り味に差が出ることがある。"
            "海に開いた水面では潮位や流れが加わる場合があるが、常滑のように潮位影響を実質除外する場もある。"
        ),
        "汽水": (
            "海水と淡水が混ざる水面。場によって塩分や流れの条件が変わり、潮位の影響を受けるケースもある。"
            "水質だけで決めず、その場の水門・河川流・潮位条件までセットで見る。"
        ),
    }

    lines = [f"🌊 **{kind}の見方**"]

    if asks_wind:
        if kind == "淡水":
            lines.append(
                "風の影響: **淡水だから風に強い/弱い、と一律には言えない**。"
                "潮流の影響が少ないぶん、当日は風向・風速・波高・水面形状の影響を分けて評価しやすい。"
            )
        elif kind == "海水":
            lines.append(
                "風の影響: 風だけでなく**潮位・流れとの組み合わせ**を見る。"
                "同じ追い風/向かい風でも、満潮・干潮や水面の開け方で1マークの流れ方が変わる。"
            )
        else:
            lines.append(
                "風の影響: **風＋潮・河川流**をセットで見る。"
                "汽水は場ごとの差が大きいので、風向だけで決め打ちしない。"
            )
        lines.append("向かい風はSTの踏み込みや伸び、追い風は1マークでの流れや差し場に影響しうる。")
        return "\n".join(lines)

    if asks_start:
        lines.append(
            "スタート: 水質だけでSTを決めない。**風向・風速、起こし位置、進入、選手のST傾向**を優先。"
            "淡水/海水の違いは乗り味の補助材料として扱う。"
        )
        return "\n".join(lines)

    if asks_turn:
        lines.append(
            f"ターン/乗り味: {basics[kind]} "
            "展示では1マークの入り、艇の掛かり、出口の押し、ターン後の加速まで見る。"
        )
        return "\n".join(lines)

    if asks_motor:
        lines.append(
            "モーター: 水質だけで機力評価は決めない。展示タイム、直線の伸び、出足・回り足、"
            "そのモーターの近況を同じ水面条件で照らし合わせる。"
        )
        return "\n".join(lines)

    if asks_tide:
        if kind == "淡水":
            lines.append("潮: **淡水水面は基本的に潮位差を予想材料にしない**。ただし河川なら流れや増減水は別物として確認。")
        else:
            lines.append("潮: 場ごとに影響度が違う。潮位対象場では満潮/干潮と風向を重ねて見る。")
        return "\n".join(lines)

    if asks_feature or explicit:
        lines.append(f"特徴: {basics[kind]}")
        lines.append("予想では水質単独で決めず、**風・波・進入・展示ST・モーター・場特性**とセットで使う。")
        return "\n".join(lines)

    return None


def water_type_list_answer_sync(question: str, user_id: int) -> Optional[str]:
    """Answer cross-venue water-type questions such as '淡水の場は？'."""
    q = _norm_knowledge_text(question)
    targets = [kind for kind in ("淡水", "海水", "汽水") if kind in q]
    if not targets:
        return None
    if len(targets) == 1 and not _venue_from_question(question):
        _water_context_by_user[user_id] = (targets[0], time.monotonic())

    # Avoid stealing single-venue questions such as "児島は海水？".
    if _venue_from_question(question):
        return None

    list_words = ["どこ", "どの場", "の場", "一覧", "全部", "教えて", "何場", "どれ"]
    if not any(word in q for word in list_words):
        return None

    tide_data = _load_json_file_cached(VENUE_TIDE_PATH, "venue_tide_profiles", 300)
    venues = tide_data.get("venues") or {}
    lines = ["🌊 **水質別ボートレース場**"]
    for kind in targets:
        matched = []
        for jcd, row in venues.items():
            if str(row.get("water_type") or "") != kind:
                continue
            venue = str(row.get("venue") or "").strip()
            if venue:
                matched.append((str(jcd).zfill(2), venue))
        matched.sort(key=lambda item: item[0])
        names = [venue for _, venue in matched]
        if names:
            lines.append(f"{kind}: **{'・'.join(names)}**（{len(names)}場）")
        else:
            lines.append(f"{kind}: 該当場をデータから確認できませんでした。")

    lines.append("気になる場名を続けて聞けば、潮・風・コース傾向まで掘れるで。")
    return "\n".join(lines)


def venue_knowledge_answer_sync(question: str) -> Optional[str]:
    venue = _venue_from_question(question)
    if not venue:
        return None
    q = _norm_knowledge_text(question)
    if not any(word in q for word in [
        "特徴", "水面", "水質", "潮", "干満", "満潮", "干潮",
        "海水", "汽水", "淡水", "どんな場", "どんな水面",
        "イン", "ダッシュ", "センター", "アウト", "まくり", "捲り",
        "差し", "風", "向かい風", "追い風", "うねり", "波", "スタート",
        "コース", "狙い目", "得意", "荒れ"
    ]):
        return None

    jcd = VENUE_TO_JCD.get(venue)
    tide_data = _load_json_file_cached(VENUE_TIDE_PATH, "venue_tide_profiles", 300)
    tactical_data = _load_json_file_cached(VENUE_TACTICAL_PATH, "venue_tactical_priors", 300)
    row = ((tide_data.get("venues") or {}).get(str(jcd)) or {}) if jcd else {}
    tactical = ((tactical_data.get("venues") or {}).get(str(jcd)) or {}) if jcd else {}
    official = _official_venue_features_sync(venue)

    if not row and not tactical and not official:
        return None

    lines = [f"🌊 **{venue}の水面メモ**"]
    water = row.get("water_type")
    if water:
        lines.append(f"水質: **{water}**")

    if row:
        if row.get("tidal_difference"):
            weight = str(row.get("weight") or "normal")
            weight_label = {
                "strong": "重要度高め",
                "thresholded": "条件付きで評価",
                "normal": "通常評価",
            }.get(weight, weight)
            lines.append(f"干満差: **あり**｜潮位は予想材料（{weight_label}）")
        else:
            reason = row.get("exclusion_reason")
            lines.append("干満差: **予想では基本的に除外**")
            if reason:
                lines.append(f"理由: {reason}")

    if official.get("race_feature"):
        lines.append(f"レース特徴: {official['race_feature']}")
    if official.get("water_feature"):
        lines.append(f"水面特性: {official['water_feature']}")

    course1 = ((official.get("courses") or {}).get("1") or {}).get("win_pct")
    if course1 is None and tactical.get("course1_win_pct") is not None:
        course1 = float(tactical["course1_win_pct"])
    if course1 is not None:
        period = official.get("period") or tactical.get("period") or "直近掲載期間"
        lines.append(f"直近データ: **1コース1着率 {float(course1):.1f}%**（{period}）")

    outer = _dominant_outer_course(official)
    if outer and any(k in q for k in ["特徴", "イン", "ダッシュ", "センター", "アウト", "まくり", "捲り", "差し", "コース", "狙い目"]):
        course, rate = outer
        method_row = ((official.get("courses") or {}).get(str(course)) or {}).get("methods") or {}
        usable = {k: float(v) for k, v in method_row.items() if k not in {"逃げ", "恵まれ"} and float(v) > 0}
        method_text = ""
        if usable:
            method, method_rate = max(usable.items(), key=lambda item: item[1])
            method_text = f"｜主な決まり手は{method} {method_rate:.1f}%"
        lines.append(f"外側で1着率が最も高いのは **{course}コース {rate:.1f}%**{method_text}")

    lines.append("※場の傾向は固定せず、当日の風・展示ST・進入・モーター気配を優先。")
    return "\n".join(lines)


def encyclopedia_answer_sync(question: str, user_id: int) -> Optional[str]:
    water_list = water_type_list_answer_sync(question, user_id)
    if water_list:
        return water_list

    water_concept = water_type_concept_answer_sync(question, user_id)
    if water_concept:
        return water_concept

    venue_answer = venue_knowledge_answer_sync(question)
    if venue_answer:
        return venue_answer

    data = _load_json_file_cached(ENCYCLOPEDIA_PATH, "boat_encyclopedia", 300)
    entries = data.get("entries") or []
    if not entries:
        return None

    q = _norm_knowledge_text(question)
    if any(word in q for word in ["何が聞ける", "なにが聞ける", "質問例", "競艇事典", "使い方"]):
        return (
            "📚 **質問くん・競艇事典**\n"
            "用語・決まり手・展示・進入・風/潮・モーター・選手成績・コース別成績・"
            "当日結果・場別的中率まで聞けるで。\n"
            "例: 「ツケマイって何？」「3がツケマイなら4は？」「若松8Rの1号艇データ」"
            "「常滑は潮見る？」「桐生1Rの結果」「今の常滑の的中率」"
        )

    candidates = []
    for entry in entries:
        aliases = [entry.get("key")] + list(entry.get("aliases") or [])
        for alias in aliases:
            norm = _norm_knowledge_text(alias)
            if norm and norm in q:
                candidates.append((len(norm), entry))
                break

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        entry = candidates[0][1]
        key = str(entry.get("key") or entry.get("title") or "")
        if key:
            _encyclopedia_context_by_user[user_id] = (key, time.monotonic())
        title = entry.get("title") or key
        answer = entry.get("answer") or ""
        return f"📘 **{title}**\n{answer}"

    # Lightweight conversational follow-up: "それもう少し詳しく" etc.
    if len(q) <= 18 and any(word in q for word in ["それ", "もっと詳しく", "詳しく", "例えば", "どういう時"]):
        ctx = _encyclopedia_context_by_user.get(user_id)
        if ctx and time.monotonic() - ctx[1] <= 900:
            key = ctx[0]
            for entry in entries:
                if str(entry.get("key") or "") == key:
                    return (
                        f"📘 **{entry.get('title') or key}**\n"
                        f"{entry.get('answer') or ''}\n"
                        "気になる条件があれば、場名・レース番号・艇番まで付けて聞けば実データ側も見にいけるで。"
                    )
    return None


async def maybe_answer_encyclopedia(question: str, user_id: int) -> Optional[str]:
    try:
        return await asyncio.to_thread(encyclopedia_answer_sync, question, user_id)
    except Exception as e:
        print(f"[encyclopedia] {type(e).__name__}: {e}", flush=True)
        return None



async def recent_water_type_from_history(message: discord.Message, max_items: int = 16) -> Optional[str]:
    """Resolve the most recent explicit water type from this user's Discord history."""
    try:
        recent = [m async for m in message.channel.history(limit=max_items, before=message)]
    except (discord.Forbidden, discord.HTTPException):
        return None

    # discord.py history is newest-first by default.
    for item in recent:
        try:
            if item.author.id != message.author.id:
                continue
        except AttributeError:
            continue
        text = _norm_knowledge_text(item.content or "")
        for kind in ("淡水", "海水", "汽水"):
            if kind in text:
                return kind
    return None


async def recent_conversation_text(message: discord.Message, max_items: int = 12) -> str:
    """Build user-scoped conversation memory from Discord history.

    This survives Render restarts because Discord itself is the source of truth.
    Only the current user's messages and bot replies that reference those
    messages are included, avoiding cross-user context leakage in shared channels.
    """
    try:
        recent = [m async for m in message.channel.history(limit=40, before=message)]
    except (discord.Forbidden, discord.HTTPException):
        return ""

    user_message_ids = {
        m.id for m in recent
        if getattr(m.author, "id", None) == message.author.id
    }
    bot_id = getattr(client.user, "id", None)
    selected: list[str] = []

    for item in reversed(recent):
        author_id = getattr(item.author, "id", None)
        text = message_text(item).strip()
        if not text:
            continue
        text = text[:900]

        if author_id == message.author.id:
            selected.append(f"ユーザー: {text}")
            continue

        if bot_id is not None and author_id == bot_id:
            ref = getattr(item, "reference", None)
            ref_id = getattr(ref, "message_id", None) if ref else None
            if ref_id in user_message_ids:
                selected.append(f"バディ: {text}")

    selected = selected[-max_items:]
    joined = "\n".join(selected)
    return joined[-6500:]


def build_instructions() -> str:
    return """あなたはDiscord上の「質問くん」です。役割は、ユーザーのバディ（相棒）として会話しながら、特に競艇を深く支えることです。
質問には日本語で、自然で親しみやすく、必要な時だけ詳しく答えてください。単発FAQではなく、直近の会話の流れを踏まえて会話を続けます。
予想メッセージや公式データなどの参照コンテキストが与えられた場合は、その内容を最優先してください。

会話:
- 「それ」「さっきの」「前のレース」などは、直近の会話履歴から対象を解決する。
- 履歴にない内容を「覚えている」と装わない。分からない時は、分からない範囲だけ短く明示する。
- 競艇以外の普通の質問や雑談にも自然に答えてよい。
- ユーザーの言葉づかいに少し合わせてもよいが、過度なキャラ口調にはしない。
- 回答は原則2〜8文。複雑な分析だけ必要に応じて箇条書きを使う。

競艇:
- 根拠が文脈にない数字・選手データ・結果・オッズ・展示気配を作らない。
- 「なぜこの艇を入れた？」のような質問で根拠データが無い場合は、断定せず不足している材料を明示する。
- フォーメーションは、1着/2着/3着候補と点数を具体的に説明する。
- ST、展示、逃げ率、逃し率、差し、まくり、まくり差し、チルト、前付けなどは初心者にも通じる言葉にする。
- 先マイ・ツケマイ・握りマイなどは、意味→成立条件→起こりうる展開→舟券で見る材料の順で考える。
- 先マイと1着を同一視しない。ツケマイは内艇を抑える外側のまくりの一種として扱う。
- 複数艇の展開質問は、内艇・攻め艇・後続艇の動きを条件付きで説明し、データのない着順や的中確率を断定しない。
- 選手の現在級だけで能力を決めず、取得できる場合は過去級・実績・コース別傾向・近況も別軸で見る。
- 展示STは本番STそのものではない。展示で遅れた選手が本番で踏み込む可能性など、選手特性も別材料として扱う。
- 1つの的中例に合わせるために全ロジックを崩さず、再現性のある補助材料として考える。
- ギャンブルの結果を保証しない。「絶対」「確実に勝てる」などは使わない。

競艇AIナビ内の呼称:
メイン=本線寄り、中穴くん=中配当狙い、穴くん=高配当スナイパー、厳選くん=配信数を絞った高信頼候補、日和=別視点データ、PT3/新人予想家ゆうき=既存ロジックを軸に補助情報を融合する予想系。
"""


def call_openai_sync(question: str, source: str, context_label: str, conversation: str = "") -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    input_text = f"""直近の会話:
{conversation if conversation else "(会話履歴なし)"}

今回の質問:
{question}

参照元:
{context_label}

予想・データコンテキスト:
{source if source else "(参照メッセージなし)"}
"""
    body = {
        "model": OPENAI_MODEL,
        "instructions": build_instructions(),
        "input": input_text,
        "max_output_tokens": 500,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {e.code}: {detail[:500]}") from e

    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    chunks = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    answer = "\n".join(chunks).strip()
    if not answer:
        raise RuntimeError("OpenAI response contained no text")
    return answer


async def answer_question(question: str, source: str, context_label: str, conversation: str = "") -> str:
    live = await live_venue_answer(question)
    if live:
        return live

    fallback = turn_tactics_answer(question) or glossary_answer(question, source)
    if OPENAI_API_KEY:
        try:
            return await asyncio.to_thread(call_openai_sync, question, source, context_label, conversation)
        except Exception as e:
            print(f"[openai] {type(e).__name__}: {e}", flush=True)
    if fallback:
        return fallback
    if source:
        q = question.lower()
        if any(k in q for k in ["予想", "買い目", "内容", "見せて", "教えて"]):
            preview = source.strip()
            if len(preview) > 1400:
                preview = preview[:1400] + "…"
            return f"対象レースの予想メッセージを見つけたで。\n\n{preview}"
        return (
            "対象レースの予想メッセージは見つけたで👍 "
            "ただ、聞きたいポイントがまだ広いです。"
            "「この買い目の理由は？」「1頭の根拠は？」「相手艇はなぜ？」「何点？」"
            "みたいに続けて聞いてください。"
        )
    return (
        "その質問は答えられるけど、今のメッセージだけだと参照元が足りないです。"
        "予想文をそのまま貼るか、Discordの予想メッセージのリンクを一緒に送ってください。"
    )


def question_channel(message: discord.Message) -> bool:
    channel = message.channel
    if QUESTION_CHANNEL_ID:
        if str(getattr(channel, "id", "")) == QUESTION_CHANNEL_ID:
            return True
        parent = getattr(channel, "parent", None)
        return str(getattr(parent, "id", "")) == QUESTION_CHANNEL_ID

    if getattr(channel, "name", "") == QUESTION_CHANNEL_NAME:
        return True
    parent = getattr(channel, "parent", None)
    return getattr(parent, "name", "") == QUESTION_CHANNEL_NAME


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    global _startup_test_sent
    print(
        f"[discord] logged in as {client.user} | "
        f"question_channel={QUESTION_CHANNEL_ID or QUESTION_CHANNEL_NAME} | "
        f"model={OPENAI_MODEL} | ai={'on' if OPENAI_API_KEY else 'fallback'}",
        flush=True,
    )

    if STARTUP_TEST_MESSAGE and not _startup_test_sent:
        target = None
        for guild in client.guilds:
            if QUESTION_CHANNEL_ID:
                candidate = guild.get_channel(int(QUESTION_CHANNEL_ID))
                if isinstance(candidate, discord.TextChannel):
                    target = candidate
                    break
            else:
                for candidate in guild.text_channels:
                    if candidate.name == QUESTION_CHANNEL_NAME:
                        target = candidate
                        break
                if target:
                    break

        if target:
            try:
                await target.send(
                    STARTUP_TEST_MESSAGE,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                _startup_test_sent = True
                print(f"[discord] startup test sent to #{target.name}", flush=True)
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"[discord] startup test failed: {type(e).__name__}: {e}", flush=True)
        else:
            print("[discord] startup test skipped: question channel not found", flush=True)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or not question_channel(message):
        return

    question = (message.content or "").strip()
    print(
        f"[question] received | channel={getattr(message.channel, 'name', '?')} "
        f"| user={message.author.id} | chars={len(question)}",
        flush=True,
    )
    if not question:
        try:
            await message.reply(
                "質問文を読み取れなかったで。Discord側のMessage Content Intentを確認する必要がありそうです。",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[question] empty-content reply failed: {type(e).__name__}: {e}", flush=True)
        return

    now = time.monotonic()
    last = _last_reply_by_user.get(message.author.id, 0)
    if now - last < 2.5:
        return
    _last_reply_by_user[message.author.id] = now

    async with message.channel.typing():
        try:
            effective_question = question
            venue = _venue_from_question(question)
            qnorm = _norm_knowledge_text(question)
            explicit_water = next((kind for kind in ("淡水", "海水", "汽水") if kind in qnorm), None)
            if explicit_water and not venue:
                _water_context_by_user[message.author.id] = (explicit_water, time.monotonic())

            water_follow_words = [
                "特徴", "違い", "風", "向かい風", "追い風", "波", "うねり",
                "スタート", "st", "ターン", "旋回", "乗り味", "浮力",
                "モーター", "伸び", "出足", "潮", "干満", "狙い目", "影響"
            ]
            if not explicit_water and not venue and len(question) <= 24 and any(k in qnorm for k in water_follow_words):
                history_water = await recent_water_type_from_history(message)
                if history_water:
                    _water_context_by_user[message.author.id] = (history_water, time.monotonic())
                    effective_question = f"{history_water} {question}"
                    print(f"[water-context] resolved={history_water}", flush=True)

            stats_words = ["的中率", "回収率", "roi", "成績", "調子", "今どう", "現状", "結果"]
            venue_words = [
                "特徴", "水面", "水質", "潮", "干満", "満潮", "干潮", "海水", "汽水", "淡水",
                "イン", "ダッシュ", "センター", "アウト", "まくり", "捲り", "差し",
                "風", "うねり", "波", "スタート", "コース", "狙い目", "荒れ"
            ]
            if venue and any(k in question.lower() for k in stats_words + venue_words):
                _venue_context_by_user[message.author.id] = (venue, time.monotonic())
            elif len(question) <= 24 and any(k in qnorm for k in water_follow_words):
                # Prefer history-resolved water context above. Only fall back to
                # the in-memory context when no explicit recent water type exists.
                if effective_question == question:
                    water_ctx = _water_context_by_user.get(message.author.id)
                    if water_ctx and time.monotonic() - water_ctx[1] <= 900:
                        effective_question = f"{water_ctx[0]} {question}"
                    else:
                        ctx = _venue_context_by_user.get(message.author.id)
                        if ctx and time.monotonic() - ctx[1] <= 900:
                            effective_question = f"{ctx[0]} {question}"
            elif len(question) <= 18 and any(k in question.lower() for k in stats_words + venue_words):
                ctx = _venue_context_by_user.get(message.author.id)
                if ctx and time.monotonic() - ctx[1] <= 900:
                    effective_question = f"{ctx[0]} {question}"

            # Fast-path answers that do not need a Discord history scan.
            quick = await maybe_answer_race_result(effective_question)
            if quick is None:
                quick = await live_venue_answer(effective_question)
            if quick is None:
                quick = await maybe_answer_course_stats(effective_question, "", message.author.id)
            if quick is None:
                quick = await maybe_answer_racer_data(effective_question, "", message.author.id)
            if quick is None and not message.reference and not MESSAGE_LINK_RE.search(effective_question) and not (RACE_RE.search(effective_question) or RACE_JP_RE.search(effective_question)):
                quick = turn_tactics_answer(effective_question)
            if quick is None:
                quick = await maybe_answer_encyclopedia(effective_question, message.author.id)
            if quick is None:
                quick = glossary_answer(effective_question, "")
            if quick is not None:
                await message.reply(
                    quick[:1900],
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return

            source_message = await get_reference_message(message)
            context_label = "返信/リンク先メッセージ"
            if source_message is None:
                source_message = await asyncio.wait_for(find_recent_prediction(message), timeout=15)
                context_label = "同一サーバー内の最近の予想メッセージ"

            source = message_text(source_message) if source_message else ""
            conversation = await recent_conversation_text(message)
            resolve_race_context(message.author.id, effective_question, source)
            answer = await maybe_answer_race_result(effective_question)
            if answer is None:
                answer = await maybe_answer_course_stats(effective_question, source, message.author.id)
            if answer is None:
                answer = await maybe_answer_racer_data(effective_question, source, message.author.id)
            if answer is None and turn_tactics_answer(effective_question):
                answer = await answer_question(effective_question, source, context_label, conversation)
            if answer is None:
                answer = await maybe_answer_encyclopedia(effective_question, message.author.id)
            if answer is None:
                answer = await answer_question(effective_question, source, context_label, conversation)

            if source_message and source_message.jump_url:
                answer = f"{answer}\n\n↪ 参照: {source_message.jump_url}"

            await message.reply(
                answer[:1900],
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except asyncio.TimeoutError:
            await message.reply(
                "参照先の検索に時間がかかったので一度止めました。場名＋レース番号を入れて、もう一度聞いてみてください。",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as e:
            print(f"[question] {type(e).__name__}: {e}", flush=True)
            await message.reply(
                "質問の処理中にエラーが出ました。少し時間を置いてもう一度送ってください。",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )


def wait_for_discord_api():
    """Keep the service alive during Discord global 429s before starting discord.py."""
    url = "https://discord.com/api/v10/users/@me"
    backoff = 30.0
    while True:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bot {BOT_TOKEN}",
                "User-Agent": "boat-ai-question-bot/1.0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= int(resp.status) < 300:
                    print("[discord] API preflight OK", flush=True)
                    return
        except urllib.error.HTTPError as e:
            if e.code != 429:
                print(f"[discord] preflight HTTP {e.code}; discord.py will handle login", flush=True)
                return

            raw = ""
            payload = {}
            try:
                raw = e.read().decode("utf-8", errors="replace")
                payload = json.loads(raw or "{}") if raw else {}
            except Exception:
                payload = {}

            headers = e.headers or {}
            scope = headers.get("X-RateLimit-Scope")
            global_header = headers.get("X-RateLimit-Global")
            retry_header = headers.get("Retry-After")
            cf_ray = headers.get("CF-Ray")
            retry_body = payload.get("retry_after") if isinstance(payload, dict) else None
            global_body = payload.get("global") if isinstance(payload, dict) else None
            message = payload.get("message") if isinstance(payload, dict) else None
            code = payload.get("code") if isinstance(payload, dict) else None
            print(
                "[discord] 429 diagnostic | "
                f"scope={scope!r} global_header={global_header!r} global_body={global_body!r} "
                f"retry_header={retry_header!r} retry_body={retry_body!r} "
                f"cf_ray={cf_ray!r} code={code!r} message={message!r}",
                flush=True,
            )
            print("[discord] diagnostic stop after one 429; no automatic retry", flush=True)
            while True:
                time.sleep(3600)
        except Exception as e:
            print(f"[discord] preflight skipped: {type(e).__name__}: {e}", flush=True)
            return


def run_discord_public_diagnostic_once():
    """One unauthenticated Discord request to distinguish IP-level blocking."""
    req = urllib.request.Request(
        "https://discord.com/api/v10/gateway",
        headers={"User-Agent": "boat-ai-question-bot/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(
                f"[discord-public] status={resp.status} cf_ray={resp.headers.get('CF-Ray')!r} "
                f"body={body[:200]!r}",
                flush=True,
            )
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(
            "[discord-public] HTTP diagnostic | "
            f"status={e.code} scope={e.headers.get('X-RateLimit-Scope')!r} "
            f"global_header={e.headers.get('X-RateLimit-Global')!r} "
            f"retry_header={e.headers.get('Retry-After')!r} "
            f"cf_ray={e.headers.get('CF-Ray')!r} body={raw[:300]!r}",
            flush=True,
        )
    except Exception as e:
        print(f"[discord-public] error={type(e).__name__}: {e}", flush=True)


def main():
    start_health_server()
    if DISCORD_PUBLIC_DIAGNOSTIC:
        run_discord_public_diagnostic_once()
        print("[discord-public] diagnostic stop; no bot login attempted", flush=True)
        while True:
            time.sleep(3600)

    if not DISCORD_CONNECT_ENABLED:
        print("[discord] connection disabled; health server remains online", flush=True)
        while True:
            time.sleep(3600)

    if not BOT_TOKEN:
        print("[waiting] DISCORD_BOT_TOKEN is not configured; health server remains online", flush=True)
        while True:
            time.sleep(3600)

    # Render uses rolling deploys: the old and new instances can overlap briefly.
    # Keep the HTTP health server available immediately, but delay Discord login
    # so two instances do not authenticate with the same bot token at once.
    if DISCORD_STARTUP_GRACE_SECONDS > 0:
        print(
            f"[discord] startup grace {DISCORD_STARTUP_GRACE_SECONDS:.0f}s "
            "to avoid overlapping bot logins during rolling deploy",
            flush=True,
        )
        time.sleep(DISCORD_STARTUP_GRACE_SECONDS)

    wait_for_discord_api()
    client.run(BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
