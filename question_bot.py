import asyncio
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

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

VENUES = [
    "桐生", "戸田", "江戸川", "平和島", "多摩川", "浜名湖", "蒲郡", "常滑",
    "津", "三国", "びわこ", "住之江", "尼崎", "鳴門", "丸亀", "児島",
    "宮島", "徳山", "下関", "若松", "芦屋", "福岡", "唐津", "大村",
]

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
    race = f"{races[0]}R" if races else None
    return venues, race


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
        formation = explain_formation(source)
        if formation:
            return formation
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
