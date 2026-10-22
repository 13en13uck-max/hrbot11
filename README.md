# Highrise Bot

A Highrise room bot built on the official Python SDK. It includes emotes, games,
music queue controls, profiles, an internal coins economy, custom commands,
moderation, polls, trivia, giveaways, anti-raid controls, and persistent SQLite
state.

## Setup

Use Python 3.11. The current SDK release pins dependencies that do not install
cleanly on Python 3.12.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a bot and API token in the [Highrise account settings](https://highrise.game/account/settings), then copy `.env.example` to `.env` and fill in the values. For a first run, set the variables in PowerShell directly:

```powershell
$env:ROOM_ID = "your-room-id"
$env:API_TOKEN = "your-api-token"
highrise bot:Bot $env:ROOM_ID $env:API_TOKEN
```

For a silent background launch, put `ROOM_ID=...` and `API_TOKEN=...` in the
local `.env` file, then double-click `start_bot.vbs`. It launches the actual
`bot:Bot` entrypoint without a console window. Use `stop_bot.bat` to stop only
this Highrise bot process; it does not terminate unrelated Python programs.

Set your permanent Highrise user ID in `config.json`:

```json
{
  "owner_id": "your-highrise-user-id"
}
```

The bot uses an absolute path for `bot.db`. On the first run, anyone can claim
ownership with `!setowner`; after that, only the configured owner can transfer
ownership with `!setowner @username`. The resulting `owner_id` is persisted in
`config.json`, and the owner display role is restored in the database when
needed. The owner role is protected as the highest-priority role and is always
restored during refreshes and permission checks.

While running, the bot watches `bot.py` and `main.py`. Saving new code in
either file automatically disconnects and restarts the bot with the latest
version. `!rf` / `!refresh` remains available for an immediate
owner-triggered restart.

Use `!info` to show your full profile card, or `!info @username` to show
another room member's profile. The card includes activity, time in room,
achievements, daily streak, and saved profile details.

The bot's `!give` and `!balance` commands use an internal, database-backed
coins balance:

```text
!balance
!give <user_id-or-known-username> <amount>
```

Users start with 100 internal coins. Admins can use `!tipall 5` to tip every
user currently in the room 5 gold (amounts from 1 to 100). `!autotip 5 60`
tips one user every 60 seconds in a fair round-robin order; use
`!autotip off` to stop it.


Core command groups include:

- `!help`, `!ping`, `!status`, `!uptime`, `!profile`, `!stats`, `!top`, `!rf` / `!refresh` (Owner restart)
- `!outfit1` through `!outfit10` apply inventory-backed outfit presets
- `!facts` fetches a random fact from the Useless Facts API
- `!summon @user` teleports a tagged user to the bot's location (Admin/Owner)
- `!truth @user` and `!dare @user` fetch prompts online with local fallbacks
- Use `!stop` to cancel your current looping emote
- The bot randomly roasts one room user every five minutes when the room is active
- `!emote list`, `!emote <name>`, `!emote stop`
- `!play`, `!queue`, `!skip`, `!pause`, `!resume`, `!shuffle`
- `!dice`, `!flip`, `!kms`, `!oneword`, `!slots`, `!rps`, `!guess`, `!blackjack`, `!wordchain`
- `!oneword` starts an eight-round letter game; submit with `!oneword <word>` or skip with `!skip`
- `!truth`, `!dare`, `!wyr`, `!trivia`, `!poll`, `!vote`
- `!giveaway`, `!enter`, `!bannedwords`, `!antiraid`
- `!slowmode`, `!lockchat`, `!unlockchat`, `!mute`, `!ban`, `!kick`
- `!grab @user [@user ...]` (VIP+, skips same or higher ranks)
- `!bring @user [@user ...]` (VIP+, ignores rank hierarchy)
- `!tele X Y Z` (Admin+), `!tele @user` (VIP+), `!tele @user <location>` (Mod+; target must meet the location rank unless the caller is Senior Mod+), `!tele @user X Y Z` (Co-Owner+)
- `!telecord [x] [y] [z]`, `!telecord @user [x] [y] [z]`, `!mypos`

The bot repeats its queue rules in room chat every 10 seconds while connected.

Commands requiring Highrise capabilities not exposed by the current SDK session
return an explicit unavailable response instead of claiming they need payment.
Set `admin_ids` in `config.json` to a list of trusted Highrise user IDs.

Run the local tests with:

```powershell
python -m unittest discover -s tests -v
```