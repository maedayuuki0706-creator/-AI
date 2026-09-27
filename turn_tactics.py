"""Stable turn terminology and conditional, race-independent tactics.

Official terminology for 先マイ / ツケマイ:
https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/11/y_077.html
https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/18/y_169.html
The scenario explanations are conditional reasoning, not recorded race results.
"""

import re
import unicodedata
from typing import Optional


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower().replace(" ", "").replace("　", "")


TACTICS = {
    "ツケマイ": {
        "aliases": ("ツケマイ", "つけまい", "付けマイ", "つけ回り"),
        "meaning": "外の艇が内艇に近い位置から外側を全速で回り、内艇を抑えて抜く攻め。まくりの一種。",
        "condition": "外艇の踏み込みと伸び・回り足が良く、内艇との距離を詰められる時。",
        "development": "成功すれば内艇は引き波などで失速しうる。外艇が流れれば内艇の残りや、さらに外の艇の差し場もある。",
        "ticket": "外艇の1着だけで決めず、抑えられる内艇の残りと後続艇の差し場を両方確認。",
    },
    "先マイ": {
        "aliases": ("先マイ", "先まい", "先回り"),
        "meaning": "他艇より先にターンマークを回ること。先に回るだけで1着確定という意味ではない。",
        "condition": "スタートで優位に立ち、先にマークへ入れる時。イン艇以外も先マイできる。",
        "development": "出口で艇が向いて加速すれば先行しやすい。大きく膨らむと内の差しや外の攻めが入る。",
        "ticket": "先マイ艇の1着候補に加え、旋回の膨らみと内側の差し艇を確認。",
    },
    "握りマイ": {
        "aliases": ("握りマイ", "握りまい", "握って回る", "全速ターン"),
        "meaning": "速度を落としすぎず、外を大きめに回って出口のスピードで勝負する旋回。",
        "condition": "回り足と出口の押しがあり、外側に旋回スペースを取れる時。",
        "development": "旋回が決まれば外から前へ出るが、膨らめば内の差し場が開く。",
        "ticket": "握る艇の外攻めと、空いた内を差す艇を展開別に検討。",
    },
    "小回り": {
        "aliases": ("小回り", "落としマイ", "落として回る"),
        "meaning": "速度を調整してターンマーク近くを小さく回り、内側のコースを守る旋回。",
        "condition": "内側に入れる位置と、減速後に立ち上がる出足がある時。",
        "development": "内を守りやすい反面、出口の加速が鈍ければ外の全速艇に先行される。",
        "ticket": "内艇の残りと外艇の伸び・出口の押しを比較。",
    },
    "絞り": {
        "aliases": ("絞り", "絞って", "しぼり"),
        "meaning": "スタート後に外の艇が内側へ進路を寄せ、内艇の進路や攻めを制限する動き。",
        "condition": "外艇が内艇よりスタートで前に出て、進路を取れる時。",
        "development": "内艇が抵抗すると外艇も旋回しづらくなり、さらに外の艇へ展開が向くことがある。",
        "ticket": "絞る艇だけでなく、抵抗する内艇と空いた外側の艇を確認。",
    },
    "差し場": {
        "aliases": ("差し場", "差しシロ", "差ししろ"),
        "meaning": "先に回る艇の内側などにできる、後続艇が差し込める空間。",
        "condition": "先行艇が外へ膨らむ、または外艇の攻めで内側に隙間ができる時。",
        "development": "差し艇の出足と艇の向きが良ければ出口で前に出るが、隙間が小さいと届かない。",
        "ticket": "差し場の大きさだけでなく、差す艇の回り足と先行艇の残りを確認。",
    },
    "ブロック": {
        "aliases": ("ブロック", "抵抗"),
        "meaning": "内艇などが外艇の攻めに進路を譲らず、相手の旋回を難しくする動き。",
        "condition": "攻める艇と守る艇が1マーク手前で近い位置に並ぶ時。",
        "development": "互いにロスが出れば空いた艇間を別の艇が突くことがある。",
        "ticket": "競り合う2艇だけに固定せず、展開を拾う後続艇も確認。",
    },
    "艇を合わせる": {
        "aliases": ("艇を合わせる", "艇を合わせ", "艇を併せる"),
        "meaning": "並走する相手の位置や速度に合わせて進路を取り、先行や相手の攻めへの抵抗を図る動き。",
        "condition": "1マーク手前や旋回後に相手と艇間が近い時。",
        "development": "併走が続けば両艇が速度を落とし、別の艇が追い上げる場合もある。",
        "ticket": "並走艇だけでなく、空いた内外の進路と後続艇を確認。",
    },
    "流れる": {
        "aliases": ("ターン流れ", "流れた", "流れる", "膨らむ"),
        "meaning": "ターンで艇が外側へ膨らみ、想定した旋回ラインから離れること。",
        "condition": "速度を持て余す、風や波で姿勢が乱れる、攻め合いで旋回位置が窮屈になる時。",
        "development": "内側に差し場が開きやすいが、差す艇の出足や艇間次第で先行艇も残る。",
        "ticket": "内から差す艇と外から切り込む艇の位置・間隔を確認。",
    },
}


def _boat_before(q: str, term_pattern: str) -> Optional[int]:
    match = re.search(rf"([1-6])(?:号艇|コース|号)?(?:が|の|は|で)?(?:[^\d]{{0,5}})?(?:{term_pattern})", q)
    return int(match.group(1)) if match else None


def turn_tactics_answer(question: str) -> Optional[str]:
    q = _norm(question)
    matches = [
        (len(_norm(alias)), key)
        for key, entry in TACTICS.items()
        for alias in entry["aliases"]
        if _norm(alias) in q
    ]
    if not matches:
        return None

    if "ツケマイ" in q and "先マイ" in q:
        return (
            "先マイは「ほかの艇より先にマークを回る」という順番の話。"
            "ツケマイは「外の艇が内艇に近づいて外から全速で抑える」という攻め方で、まくりの一種。"
            "先に回っても出口で流れれば差されるし、ツケマイも内艇を抑え切れなければ失敗する。"
            "スタート隊形とターン出口の足を見て展開を分けるで。"
        )

    # Compound question: preserve both tactics instead of returning a single glossary hit.
    if ("流れ" in q or "膨ら" in q) and "差し" in q and ("まくり差し" in q or "捲り差し" in q):
        return (
            "1マークで先行艇が外へ流れたら、内側が空くので差し艇には入り口ができる。"
            "外の艇のまくり差しも、艇間が開いていれば届く可能性がある。"
            "どちらが先かは艇間、ターン入口での位置、出口の押しで変わる。"
            "実際の艇番だけでは優劣を断定できないので、展示と進入も見て判断するで。"
        )

    key = max(matches)[1]
    entry = TACTICS[key]
    if key == "先マイ" and (boat := _boat_before(q, "先マイ|先まい|先回り")):
        next_boat = boat + 1 if boat < 6 else None
        others = f"外の{next_boat}号艇以降" if next_boat else "外の艇"
        return (
            f"{boat}号艇が先マイするなら、まず{boat}号艇の1マーク先取りを想定。"
            "出口で膨らめば内側からの差しが届く余地があるし、"
            f"{others}が全速で迫る展開もある。"
            "先マイ＝1着確定ではない。進入コース、ST、回り足と艇間を確認して相手を組み立てるで。"
        )
    if key == "ツケマイ" and (boat := _boat_before(q, "ツケマイ|つけまい|付けマイ|つけ回り")):
        next_boat = boat + 1 if boat < 6 else None
        outside = f"{next_boat}号艇" if next_boat else "さらに外の艇"
        return (
            f"{boat}号艇のツケマイは、内艇に近い外側を全速で回り、相手を抑える攻め。"
            f"成功すれば{boat}号艇が先行しやすいが、{outside}は攻めた艇の外を追走するか、"
            "艇間が開けばまくり差しで切り込む。"
            "攻めが流れると内艇の残りや後続の差しもあるので、着順は決め打ちしないで。"
        )
    return (
        f"**{key}**：{entry['meaning']}\n"
        f"起こる条件：{entry['condition']}\n"
        f"次の展開：{entry['development']}\n"
        f"舟券で見る所：{entry['ticket']}"
    )
