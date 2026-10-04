"""Adapters that let existing predictors use the isolated V2 sender.

No prediction logic lives here. Each adapter only resolves a webhook and sends
an already-rendered Discord message with acknowledgement.
"""
from __future__ import annotations
import os
from delivery_v2.discord_sender import post_confirmed, webhook


def send_main(content: str) -> str:
    return post_confirmed(webhook("DISCORD_WEBHOOK_URL"), content, username="競艇AI メイン")


def send_selected(content: str) -> str:
    name = "DISCORD_SELECTED_WEBHOOK_URL"
    url = os.getenv(name, "").strip() or webhook("DISCORD_WEBHOOK_URL")
    return post_confirmed(url, content, username="厳選くん")


def send_yuuki(content: str) -> str:
    url = os.getenv("PT3_DISCORD_WEBHOOK_URL", "").strip() or os.getenv("PROTO3_DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        url = webhook("PT3_DISCORD_WEBHOOK_URL")
    return post_confirmed(url, content, username="新人予想家 ゆうき")


def send_yuuki_selected(content: str) -> str:
    url = os.getenv("PT3_SELECTED_DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        url = os.getenv("DISCORD_SELECTED_WEBHOOK_URL", "").strip()
    if not url:
        url = os.getenv("PT3_DISCORD_WEBHOOK_URL", "").strip() or webhook("PROTO3_DISCORD_WEBHOOK_URL")
    return post_confirmed(url, content, username="新人予想家 ゆうき｜厳選")


def send_sokuhou(content: str) -> str:
    return post_confirmed(webhook("DISCORD_HIT_WEBHOOK_URL"), content, username="速報くん")
