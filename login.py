#!/usr/bin/env python3
"""login.py — one-time MTProto authentication for the user account
the poller will run as.

Run this ONCE, follow the prompts, and a `.session` file will be
written to TELETHON_SESSION_PATH. The poller reuses that session
file indefinitely (or until you log out / Telegram invalidates it).

Run:
    python3 login.py
"""
import os
import sys

from telethon.sync import TelegramClient


def _env(name, default=None):
    val = os.environ.get(name, default)
    if val is None:
        sys.exit(f"FATAL: {name} not set. Copy .env.example to .env "
                 f"and `source` it (or `export` the vars manually).")
    return val


SESSION_PATH = _env("TELETHON_SESSION_PATH",
                    os.path.expanduser("~/.telethon-user"))
API_ID = int(_env("TELEGRAM_API_ID"))
API_HASH = _env("TELEGRAM_API_HASH")


def main():
    print(f"Logging in. Session will be saved to {SESSION_PATH}.session")
    print(f"API ID:   {API_ID}")
    print(f"API HASH: {'*' * (len(API_HASH) - 4)}{API_HASH[-4:]}")
    print()
    print("You'll be prompted for your phone number, the SMS code "
          "Telegram sends, and your 2FA password if enabled.")
    print()
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    client.start()
    me = client.get_me()
    print()
    print(f"✅ Logged in as {me.first_name} {me.last_name or ''} "
          f"(id={me.id})")
    print(f"✅ Session saved at {SESSION_PATH}.session")
    client.disconnect()


if __name__ == "__main__":
    main()
