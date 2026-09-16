"""High-energy random commentator persona for Discord hit alerts.

This module decorates the existing hit-alert messages without changing hit
judgement, payouts, or delivery deduplication. 速報くん only adds celebration.
"""
from __future__ import annotations

import random


OPENERS = (
    "🚨🚨 **速報くんが持ってきましたァァァ！！！**",
    "🔥🔥 **速報くん、また持ってきたーーー！！！**",
    "📣🚨 **速報です！！速報くん出動ォォォ！！！**",
    "💥🎯 **来た来た来たァァァ！！速報くん参上！！！**",
    "🚤🔥 **お待たせしましたァァァ！！速報くんです！！！**",
    "🎙️🚨 **現場から速報ォォォ！！これは来たぞーーー！！！**",
    "⚡🎯 **速報くん、的中持って帰ってきましたァァァ！！！**",
    "🚨🔥 **よっしゃァァァ！！速報くんが駆け込んできたーーー！！！**",
)

PLAY_BY_PLAY = (
    "**展開通りィィ！！ {head}号艇がズッポシ！！！🎯🔥**",
    "**ここで{head}号艇ーーー！！ズッポシ決まったァァァ！！！**",
    "**読みがハマったァァァ！！ {head}号艇が先頭で持ってきたーーー！！！**",
    "**その展開待ってましたァァ！！ {head}号艇キターーー！！！**",
    "**隊形ハマったァァァ！！ {head}号艇がズッポシ頭！！！**",
    "**これこれこれェェェ！！ {head}号艇が突き抜けたーーー！！！**",
    "**狙い通りィィィ！！ {head}号艇がドンピシャで先頭ォォォ！！！**",
    "**見えた展開そのままァァ！！ {head}号艇が持ってったーーー！！！**",
    "**バチッとハマったァァァ！！ {head}号艇がズッポシ！！！**",
    "**来たぞォォォ！！ {head}号艇、読み通りの頭ァァァ！！！**",
)

NORMAL_CLOSERS = (
    "🔥 **速報くん、今日も仕事したァァァ！！！**",
    "🎯 **この一発、気持ち良すぎるーーー！！！**",
    "🚨 **的中持って帰ってきたぞォォォ！！！**",
    "💥 **よっしゃァァァ！！このまま次も行くぞーーー！！！**",
    "🔥 **これは盛り上がるゥゥゥ！！速報くん絶好調！！！**",
)

MID_ODDS_CLOSERS = (
    "🟡🔥 **中穴ぶち抜きィィィ！！！これは気持ちいい！！！**",
    "🟡🎯 **中穴ハマったァァァ！！速報くん大興奮！！！**",
    "🟡💥 **この配当帯を持ってくるゥゥゥ！！ナイス中穴！！！**",
    "🟡🚨 **中穴キターーー！！読みと買い目が噛み合ったァァァ！！！**",
)

LONGSHOT_CLOSERS = (
    "🔴💣 **穴ぶち抜きィィィ！！！速報くん暴れてます！！！**",
    "🔴🔥 **穴キターーー！！これはテンション上がるゥゥゥ！！！**",
    "🔴🎯 **この穴を持ってきたァァァ！！最高ォォォ！！！**",
    "🔴💥 **穴AI炸裂ゥゥゥ！！速報くん止まりません！！！**",
)

MANSHU_CLOSERS = (
    "🚨💰🔥 **万舟ィィィ！！！速報くん、とんでもないの持ってきましたァァァ！！！**",
    "💥💰 **万舟ぶち抜きーーー！！！これは祭りじゃァァァ！！！**",
    "🚨🚨💰 **緊急速報ォォォ！！万舟捕獲ゥゥゥ！！！**",
    "🔥💰🎯 **万舟キターーー！！！速報くん本日最大級の大騒ぎ！！！**",
    "💣💰 **ドカンと万舟ゥゥゥ！！これは気持ち良すぎる！！！**",
)


def _winner_head(winner: str) -> str:
    head = str(winner or "").split("-", 1)[0].strip()
    return head if head.isdigit() else "勝ち艇"


def _closers(stream: str, payout: int) -> tuple[str, ...]:
    if payout >= 10000:
        return MANSHU_CLOSERS
    if stream == "mid_odds":
        return MID_ODDS_CLOSERS
    if stream == "longshot":
        return LONGSHOT_CLOSERS
    return NORMAL_CLOSERS


def hype_lines(winner: str, payout: int, stream: str = "normal") -> tuple[str, str, str]:
    """Return one random opener, play-by-play call, and closer."""
    head = _winner_head(winner)
    return (
        random.choice(OPENERS),
        random.choice(PLAY_BY_PLAY).format(head=head),
        random.choice(_closers(stream, payout)),
    )


def _decorate(message: str, winner: str, payout: int, stream: str) -> str:
    opener, call, closer = hype_lines(winner, payout, stream)
    # Keep the existing factual card intact between the two hype blocks.
    return "\n".join((opener, call, "", message, "", closer))


def install(hit_alerts_module) -> None:
    """Wrap hit_alerts message builders once with 速報くん commentary."""
    if getattr(hit_alerts_module, "_sokuhou_character_installed", False):
        return

    original_message = hit_alerts_module._message
    original_opportunity_message = hit_alerts_module._opportunity_message

    def message(row: dict, winner: str, payout: int, result: dict) -> str:
        base_message = original_message(row, winner, payout, result)
        return _decorate(base_message, winner, payout, "normal")

    def opportunity_message(row: dict, winner: str, payout: int) -> str:
        base_message = original_opportunity_message(row, winner, payout)
        stream = str(row.get("stream") or "longshot")
        return _decorate(base_message, winner, payout, stream)

    hit_alerts_module._message = message
    hit_alerts_module._opportunity_message = opportunity_message
    hit_alerts_module._sokuhou_character_installed = True
