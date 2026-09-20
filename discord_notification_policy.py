"""Discord push policy: only selected predictions and hit alerts notify everyone."""

# Discord's SUPPRESS_NOTIFICATIONS flag also suppresses desktop notifications.
# https://docs.discord.com/developers/resources/message#message-flags
SUPPRESS_NOTIFICATIONS = 1 << 12


def message_payload(content: str, *, notify_everyone: bool = False) -> dict:
    """Keep ordinary posts silent; explicitly opt selected/hit alerts into pings."""
    if notify_everyone:
        if not content.startswith("@everyone\n"):
            content = "@everyone\n" + content
        return {
            "content": content,
            "allowed_mentions": {"parse": ["everyone"]},
            "flags": 0,
        }
    return {
        "content": content,
        "allowed_mentions": {"parse": []},
        "flags": SUPPRESS_NOTIFICATIONS,
    }
