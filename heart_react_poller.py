#!/usr/bin/env python3
"""heart_react_poller.py — long-running MTProto poller that catches
heart-reactions on bot-sent messages in 1:1 private DMs, where the
Telegram Bot API can't see them.

The Bot API requires the bot to be an administrator in the chat to
receive `message_reaction` updates — but private DMs have no admin
concept, so reactions on bot messages are unreachable from the bot
side. The user's own MTProto session, however, can read them.

Verified empirically: Telethon's push-mode `events.Raw` does NOT fire
on `UpdateMessageReactions` for these reactions. But polling
`client.get_messages(bot, limit=N)` returns each Message's
`.reactions` field with the current state. So we poll on a schedule
and act on new hearts.

Configuration: copy `.env.example` to `.env`, fill in the three
values, and run. See README.md for the full setup walkthrough.
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime

from telethon import TelegramClient
from telethon.tl.types import ReactionEmoji


# ── CONFIG ────────────────────────────────────────────────────────────
def _env(name, default=None):
    val = os.environ.get(name, default)
    if val is None:
        sys.exit(f"FATAL: {name} not set. Copy .env.example to .env and fill it in.")
    return val


SESSION_PATH = _env("TELETHON_SESSION_PATH",
                    os.path.expanduser("~/.telethon-user"))
API_ID = int(_env("TELEGRAM_API_ID"))
API_HASH = _env("TELEGRAM_API_HASH")
BOT_USERNAME = _env("BOT_USERNAME")  # e.g. "@your_bot_username"

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "8"))
MESSAGES_LOOKBACK = int(os.environ.get("MESSAGES_LOOKBACK", "100"))
TODAY_ONLY = os.environ.get("TODAY_ONLY", "1") == "1"
SEEN_FILE = os.environ.get("SEEN_FILE",
                            os.path.expanduser("~/.heart_react_seen.json"))
SEEN_CAP = int(os.environ.get("SEEN_CAP", "100"))


# ── HEART EMOJI SET ───────────────────────────────────────────────────
# Telegram's standard reaction emoji include several heart variants.
# Edit this set to match whatever you want to treat as a "save" trigger.
HEART_EMOJIS = {
    "❤", "❤️", "🧡", "💛", "💚", "💙", "💜",
    "🤎", "🖤", "🤍",
    "💖", "💗", "💓", "💕", "💞", "💘",
    "❣", "❣️", "💟",
    "❤‍🔥", "❤️‍🔥",
}


# ── DEDUPE STATE ──────────────────────────────────────────────────────
def _seen_load():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _seen_save(seen):
    capped = sorted(seen)[-SEEN_CAP:]
    os.makedirs(os.path.dirname(SEEN_FILE) or ".", exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(capped, f)


# ── HELPERS ───────────────────────────────────────────────────────────
def _is_heart(reaction_obj):
    return (isinstance(reaction_obj, ReactionEmoji)
            and reaction_obj.emoticon in HEART_EMOJIS)


# ── REPLACE THIS WITH YOUR OWN ACTION ─────────────────────────────────
def on_heart(message, message_epoch):
    """Called once per new heart. Override this to do whatever you want
    when the user hearts a bot message — save to a database, send a
    follow-up, kick off a workflow, etc.

    Args:
        message: the Telethon Message object — has .id, .date, .text
                 (caption), .media, etc.
        message_epoch: int — unix epoch seconds of the message's date.
                       Useful for correlating to your own logs/DB if
                       you stamp records by timestamp.
    """
    print(
        f"[heart] msg_id={message.id} epoch={message_epoch} "
        f"caption={(message.text or message.message or '')[:80]!r}",
        flush=True,
    )


# ── MAIN LOOP ─────────────────────────────────────────────────────────
async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("FATAL: session not authorized. Run login.py first.")

    bot_entity = await client.get_entity(BOT_USERNAME)
    me = await client.get_me()
    print(f"[heart-react-poller] connected as {me.first_name} "
          f"(id={me.id}); polling DM with {BOT_USERNAME} "
          f"(bot_id={bot_entity.id}) every {POLL_INTERVAL}s, "
          f"lookback={MESSAGES_LOOKBACK} msgs, "
          f"today_only={TODAY_ONLY}", flush=True)

    seen = _seen_load()
    print(f"[heart-react-poller] dedupe state loaded: {len(seen)} "
          f"prior msg_id(s)", flush=True)

    while True:
        try:
            msgs = await client.get_messages(bot_entity,
                                             limit=MESSAGES_LOOKBACK)
        except Exception as e:
            print(f"[heart-react-poller] poll error: {e}", flush=True)
            await asyncio.sleep(POLL_INTERVAL)
            continue

        new_fires = 0
        today_local = datetime.now().astimezone().date()
        for m in msgs:
            if getattr(m, "sender_id", None) != bot_entity.id:
                continue
            if TODAY_ONLY:
                try:
                    if m.date.astimezone().date() != today_local:
                        continue
                except Exception:
                    pass
            rx = getattr(m, "reactions", None)
            if rx is None:
                continue
            results = getattr(rx, "results", []) or []
            has_heart = any(_is_heart(getattr(r, "reaction", None))
                            for r in results)
            if not has_heart:
                # Reaction removed — drop dedupe stamp so re-add fires.
                seen.discard(m.id)
                continue
            if m.id in seen:
                continue
            seen.add(m.id)
            new_fires += 1
            try:
                msg_epoch = int(m.date.timestamp())
            except Exception:
                msg_epoch = int(time.time())
            on_heart(m, msg_epoch)

        if new_fires:
            _seen_save(seen)

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
