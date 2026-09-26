import asyncio
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from zoneinfo import ZoneInfo

import discord

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
QUESTION_CHANNEL_NAME = os.getenv("DISCORD_QUESTION_CHANNEL_NAME", "質問").strip()
QUESTION_CHANNEL_ID = os.getenv("DISCORD_QUESTION_CHANNEL_ID", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
PORT = int(os.getenv("PORT", "10000"))
STARTUP_TEST_MESSAGE = os.getenv("STARTUP_TEST_MESSAGE", "").strip()
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


def build_instructions() -> str:
    return """あなたは競艇AIナビのDiscord質問係です。
ユーザーの質問に、日本語で短く分かりやすく答えてください。
予想メッセージの文脈が与えられた場合は、その内容を最優先で説明してください。

重要:
- 根拠が文脈にない数字・選手データ・結果・オッズ・展示気配を作らない。
- 「なぜこの艇を入れた？」のような質問で根拠データが無い場合は、断定せず「このメッセージだけでは根拠データまで確認できない」と明示する。
- フォーメーションは、1着/2着/3着候補と点数を具体的に説明する。
- ST、展示、逃げ率、逃し率、差し、まくり、まくり差し、チルト、前付けなどは初心者にも通じる言葉にする。
- ギャンブルの結果を保証しない。「絶対」「確実に勝てる」などは使わない。
- 回答は原則2〜6文。長くなる時は箇条書きを3〜5個まで。
- 競艇AIナビ内の呼称: メイン=本線寄り、中穴くん=中配当狙い、穴くん=高配当スナイパー、厳選くん=配信数を絞った高信頼候補、日和=別視点データ、PT3=既存を軸に日和を補助利用する融合系。
"""


def call_openai_sync(question: str, source: str, context_label: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    input_text = f"""質問:
{question}

参照元:
{context_label}

予想・会話コンテキスト:
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


async def answer_question(question: str, source: str, context_label: str) -> str:
    fallback = glossary_answer(question, source)
    if OPENAI_API_KEY:
        try:
            return await asyncio.to_thread(call_openai_sync, question, source, context_label)
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
    if QUESTION_CHANNEL_ID:
        return str(message.channel.id) == QUESTION_CHANNEL_ID
    return getattr(message.channel, "name", "") == QUESTION_CHANNEL_NAME


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
    if not question:
        return

    now = time.monotonic()
    last = _last_reply_by_user.get(message.author.id, 0)
    if now - last < 2.5:
        return
    _last_reply_by_user[message.author.id] = now

    async with message.channel.typing():
        source_message = await get_reference_message(message)
        context_label = "返信/リンク先メッセージ"
        if source_message is None:
            source_message = await find_recent_prediction(message)
            context_label = "同一サーバー内の最近の予想メッセージ"

        source = message_text(source_message) if source_message else ""
        resolve_race_context(message.author.id, question, source)
        answer = await maybe_answer_course_stats(question, source, message.author.id)
        if answer is None:
            answer = await answer_question(question, source, context_label)

        if source_message and source_message.jump_url:
            answer = f"{answer}\n\n↪ 参照: {source_message.jump_url}"

        await message.reply(
            answer[:1900],
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )


def main():
    start_health_server()
    if not BOT_TOKEN:
        print("[waiting] DISCORD_BOT_TOKEN is not configured; health server remains online", flush=True)
        while True:
            time.sleep(3600)
    client.run(BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
