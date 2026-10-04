"""Only transport routing; all prediction selection stays in existing engines."""
import os
from delivery_v2.discord_sender import post_confirmed, webhook


def send_main(content):
    return post_confirmed(webhook('DISCORD_WEBHOOK_URL'), content, username='競艇AI メイン')


def send_selected(content):
    url = os.getenv('DISCORD_SELECTED_WEBHOOK_URL', '').strip() or webhook('SELECTED_DISCORD_WEBHOOK_URL')
    return post_confirmed(url, content, username='通常厳選｜厳選くん', notify_everyone=True)


def send_yuuki(content):
    url = os.getenv('PT3_DISCORD_WEBHOOK_URL', '').strip() or webhook('PROTO3_DISCORD_WEBHOOK_URL')
    return post_confirmed(url, content, username='新人予想家 ゆうき')


def send_yuuki_selected(content):
    url = os.getenv('PT3_SELECTED_DISCORD_WEBHOOK_URL', '').strip() or webhook('DISCORD_SELECTED_WEBHOOK_URL')
    return post_confirmed(url, content, username='ゆうき厳選｜新人予想家 ゆうき', notify_everyone=True)


def send_mid(content):
    return post_confirmed(webhook('DISCORD_WEBHOOK_MID_ODDS'), content, username='中穴くん')


def send_mid_selected(content):
    url = os.getenv('DISCORD_WEBHOOK_MID_ODDS_SELECTED', '').strip() or webhook('DISCORD_SELECTED_WEBHOOK_URL')
    return post_confirmed(url, content, username='中穴厳選｜中穴くん', notify_everyone=True)


def send_longshot(content):
    return post_confirmed(webhook('DISCORD_WEBHOOK_LONGSHOT'), content, username='穴くん')


def send_sokuhou(content):
    return post_confirmed(webhook('DISCORD_HIT_WEBHOOK_URL'), content, username='速報くん', notify_everyone=True)


SENDERS = {'main': send_main, 'selected': send_selected, 'yuuki': send_yuuki,
           'yuuki_selected': send_yuuki_selected, 'mid_odds': send_mid,
           'mid_odds_selected': send_mid_selected, 'longshot': send_longshot, 'sokuhou': send_sokuhou}
