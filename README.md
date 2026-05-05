# telegram-bot-reaction-listener-mtproto

Detect heart-reactions on bot-sent messages in **1:1 private Telegram
DMs**, where the Bot API can't see them.

## The problem

You have a Telegram bot that sends photos (or any messages) to a user
in a 1:1 private chat. You'd like to detect when the user adds a
reaction (e.g. ❤️) to one of those bot messages — to trigger a save,
log an event, send a follow-up, etc.

The Bot API has an Update type for this called `message_reaction`. If
you read [the spec for Bot API 9.6](https://core.telegram.org/bots/api#update),
you'll find:

> *Optional. A reaction to a message was changed by a user. **The bot
> must be an administrator in the chat** and must explicitly specify
> `"message_reaction"` in the list of `allowed_updates` to receive
> these updates. The update isn't received for reactions set by bots.*

This is repeated in [grammY's reactions guide](https://grammy.dev/guide/reactions)
and [python-telegram-bot's MessageReactionHandler docs](https://docs.python-telegram-bot.org/en/stable/telegram.ext.messagereactionhandler.html).

The catch: **a bot cannot be an administrator of a 1:1 private DM** —
admin status is a group/channel-only concept. So `message_reaction`
updates never arrive for bot-sent messages in private chats.

Verified empirically: subscribe `message_reaction` in `allowed_updates`,
run a 5-minute listener, react to a bot photo → zero events.

The Business Bot mode introduced in Bot API 7.x doesn't help either:
`MessageReactionUpdated` has no `business_connection_id` field, so
business connections don't change reaction delivery rules.

## The workaround

Read reactions from the **user's side** using MTProto. A user-account
session (Telethon) authenticated as the user themselves can read every
message in every chat that user is in — including reactions on bot
messages.

This works because the user's own MTProto session sees the chat from
the user's perspective, not the bot's. The "must be admin" rule
applies to bots reading the chat; the user reading their own DM has
no such restriction.

## What works and what doesn't

I tried two approaches with Telethon's user-account session:

| Approach | Result |
|---|---|
| `events.Raw` push-mode listener for `UpdateMessageReactions` | **Doesn't fire.** Telegram's server doesn't push these updates over MTProto for reactions on bot messages in private DMs. |
| `client.get_messages(bot, limit=N)` polling, read `.reactions` | **Works.** The reaction state is fully populated on each Message object. |

So the only working path is **polling**. Pull the recent messages
every few seconds, check each Message's `.reactions` field, fire on
any new heart you haven't seen before.

## Setup

### 1. Get an `api_id` + `api_hash`

The MTProto user API requires an app registration tied to a Telegram
user account (not a bot). Get one here:

→ <https://my.telegram.org/apps>

Sign in with the Telegram account that will host the listener (i.e.
the account that receives the bot's messages — usually your own).
Click **API development tools**, fill in any name/short-name, and
note the `api_id` and `api_hash`.

### 2. Clone, install, configure

```bash
git clone https://github.com/YOUR-USERNAME/telegram-bot-reaction-listener-mtproto.git
cd telegram-bot-reaction-listener-mtproto
pip install -r requirements.txt

cp .env.example .env
# Edit .env — fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, BOT_USERNAME,
# TELETHON_SESSION_PATH.
```

### 3. One-time login

```bash
# Load the env vars into your shell.
set -a; source .env; set +a

python3 login.py
```

You'll be prompted for your phone number, the SMS code Telegram
sends, and your 2FA password (if enabled). On success a `.session`
file is written to `TELETHON_SESSION_PATH` and reused thereafter.

### 4. Edit `on_heart()` to do whatever you need

`heart_react_poller.py` ships with a placeholder `on_heart(message,
message_epoch)` that just prints to stdout. Replace it with your real
action — call your save flow, write to a database, kick off a workflow,
whatever. The function receives the full Telethon Message object and
the message's unix epoch (useful for correlating to your own logs).

### 5. Run it

For a quick test:

```bash
python3 heart_react_poller.py
```

Tap a heart on one of the bot's messages — within ~8 seconds you'll
see `[heart] msg_id=… caption=…` print. Ctrl-C to stop.

### 6. Run as a service (systemd)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/heart-react-poller.service ~/.config/systemd/user/
# Edit the three paths in that file to point at your install.
systemctl --user daemon-reload
systemctl --user enable --now heart-react-poller.service
journalctl --user -u heart-react-poller -f
```

## Tuning

All configurable via `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `POLL_INTERVAL` | `8` | Seconds between polls. 8s feels near-instant; lower = more API calls for marginal UX gain. |
| `MESSAGES_LOOKBACK` | `100` | How many recent bot messages to scan each poll. 100 is Telegram's per-call max for `messages.GetHistory`. |
| `TODAY_ONLY` | `1` | If `1`, only consider messages whose date is today (local time). Drops yesterday's messages so the dedupe set naturally clears each midnight. |
| `SEEN_FILE` | `~/.heart_react_seen.json` | Where the dedupe state is persisted. |
| `SEEN_CAP` | `100` | Max msg_ids retained in the dedupe set. |

## Things I learned along the way

- **Telethon `events.Raw` does NOT receive `UpdateMessageReactions`
  for reactions on bot messages in 1:1 DMs.** Telegram's MTProto
  server doesn't push these updates over the user account's update
  stream — even though the data IS reachable when you ask for it
  directly. Don't waste time trying push-mode listeners. Polling is
  the only approach that works.

- **Polling cost is negligible.** `messages.GetHistory` is one of the
  cheapest MTProto calls. ~10K calls/day at 8-second cadence is well
  within rate limits — no flood-wait risk for normal use.

- **Dedupe is essential.** Polling is stateless; without a dedupe
  set every poll would re-fire on hearts from previous polls.
  Persist the dedupe set across restarts so a service restart doesn't
  fire on yesterday's hearts.

- **Bot-side `message_id` ≠ user-side `message_id`**: in MTProto,
  each peer sees its own message numbering. The `msg_id` your bot
  got from `sendPhoto` is NOT the same `m.id` your user-account
  session sees. If you need to correlate, do it through external
  state (timestamp, caption text, your own log) — not by passing
  message_ids.

- **Polling cadence trade-off**: 8 seconds feels near-instant. 30
  seconds feels laggy. 3-second polling adds load without meaningful
  UX gain. 8s is the sweet spot.

## What this does NOT solve

- **Reactions on other users' messages** in groups/supergroups. If
  you need that for a multi-user chat, the bot does need to be an
  admin in the chat and the Bot API works the standard way.
- **Bot-set reactions** (the bot reacting to user messages). The Bot
  API has [`setMessageReaction`](https://core.telegram.org/bots/api#setmessagereaction)
  for this — works in 1:1 DMs without admin status.
- **Latency below ~5 seconds** without bumping the poll rate. If you
  need sub-second reaction-to-action timing, you'll need a more
  aggressive cadence and accept the API call volume.

## Summary

The Bot API will **never** deliver `message_reaction` updates for
reactions on bot-sent messages in 1:1 private DMs — the "must be
administrator" rule structurally excludes them, and admin status
doesn't apply to private DMs in the first place.

But the data IS reachable: a user-account MTProto session can poll
for it. ~150 lines of Telethon, deployed as a long-running service,
gives you near-instant heart-reaction handling on your bot's photos.
No new servers needed beyond what you already have for the bot.

## License

MIT — see [LICENSE](LICENSE).
