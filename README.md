# Discord MCP (Python/FastMCP)

This repo now runs the Discord admin MCP as a Python/FastMCP service instead of Java/Spring.

It provides:

- Streamable HTTP MCP on `/mcp` port `8085`
- Discord admin and moderation tools backed by the Discord REST API
- Docker Compose runtime for local and production use
- A plugin wrapper at `/Users/vaughndazo/plugins/discord-admin-mcp`

## 0. Current Runtime

- Local runtime: `/Users/vaughndazo/Documents/LDX/Apps/discord-mcp`
- Local endpoint: `http://localhost:8085/mcp`
- Production/plugin endpoint: `http://100.127.158.115:8085/mcp`

## 1. Configure Environment

```bash
cp .env.example .env
```

Set at minimum:

```env
DISCORD_TOKEN=your_bot_token
DISCORD_GUILD_ID=optional_default_guild_id
MCP_HOST=0.0.0.0
MCP_PORT=8085
LOG_LEVEL=INFO
DISCORD_API_BASE_URL=https://discord.com/api/v10
```

## 2. Run Locally

```bash
docker compose up -d --build
docker compose ps
```

Quick runtime check:

```bash
docker compose exec -T discord-mcp python - <<'PY'
from src.server import healthcheck
print(healthcheck())
PY
```

## 3. Tool Surface

Read and inspect:

- `healthcheck`
- `get_server_info`
- `get_member_access`
- `list_channels`
- `find_channel`
- `get_channel_info`
- `find_category`
- `list_channels_in_category`
- `list_channel_permission_overwrites`
- `read_messages`
- `get_attachment`
- `get_user_id_by_name`
- `read_private_messages`
- `list_roles`
- `get_bans`
- `list_active_threads`
- `list_guild_scheduled_events`
- `get_guild_scheduled_event_users`
- `list_invites`
- `get_invite_details`
- `list_emojis`
- `get_emoji_details`
- `list_webhooks`

Write and moderation:

- channel and category create, edit, move, delete
- channel permission overwrite upsert and delete
- channel and DM message send, edit, delete
- message reactions add and remove
- role create, edit, delete, assign, remove
- member kick, ban, unban, timeout, nickname, voice state updates
- voice and stage channel create and edit
- scheduled event create, edit, delete
- invite create and delete
- emoji create, edit, delete
- webhook create, delete, send message

## 4. Compatibility Notes

- Existing tool names are preserved.
- Existing camelCase input names are preserved.
- Outputs are now structured JSON objects instead of free-form strings.
- `guildId` remains optional when `DISCORD_GUILD_ID` is configured.

## 5. Plugin Wiring

Plugin files live at:

- `/Users/vaughndazo/plugins/discord-admin-mcp/.codex-plugin/plugin.json`
- `/Users/vaughndazo/plugins/discord-admin-mcp/.mcp.json`
- `/Users/vaughndazo/plugins/discord-admin-mcp/skills/*`

The plugin start script should launch this repo with Docker Compose instead of pulling the old upstream Java image.

## Member access inspection

`get_member_access(userId, guildId=None, includeChannels=True, channelLimit=25)`
uses only GET requests. `userId` is required; `guildId` defaults to
`DISCORD_GUILD_ID`. IDs must be numeric strings of 1–20 digits. `includeChannels`
is a boolean and `channelLimit` is an integer from 1 to 100; invalid values are
rejected before REST requests. Disabling channels skips both channel discovery
requests and membership probes. No member enumeration or webhook reads occur.

The result contains selected member identity fields, assigned roles (at most 250),
the separate @everyone role, effective guild permissions, timeout status, and up to
`channelLimit` channel summaries. Permission masks are decimal strings with canonical
permission names, including `SET_VOICE_CHANNEL_STATUS` (48), `PIN_MESSAGES` (51),
and `BYPASS_SLOWMODE` (52). Channels precede active threads in API order;
`channels_truncated` reports truncation of the discovered snapshot, not completeness
of Discord coverage. Text fields are capped at 512 characters. Raw API objects and
error bodies are excluded; the configured bot token and webhook URL tokens are redacted.

Computation unions @everyone and assigned role permissions, grants owners and
administrators all known bits, then applies channel @everyone overwrites, aggregated
role denies then allows, and member denies then allows. Category overwrites are not
applied a second time: Discord returns the channel's own overwrites, including synced
ones. Active timeouts retain only VIEW_CHANNEL and READ_MESSAGE_HISTORY (without
granting either); owners and administrators are exempt. Channel implicit denials
remove channel permissions without VIEW_CHANNEL, dependent text-send permissions
without SEND_MESSAGES, and voice dependencies without CONNECT. In voice/stage
channels lack of CONNECT also removes channel/role management permissions.

Threads use their parent channel's overwrites, never thread-local overwrites.
SEND_MESSAGES_IN_THREADS controls thread sending independently of SEND_MESSAGES.
`permission_source_id` identifies the parent used. Missing parents produce unknown
permissions and access. Private threads require membership or MANAGE_THREADS;
for each returned private thread with inherited visibility and without MANAGE_THREADS,
the tool probes `GET /channels/{thread.id}/thread-members/{user.id}` for the target.
A successful response establishes membership, so inherited permissions determine
visibility and sending. Any lookup error (including 404) leaves positive access
unknown (`null`), while provable denials remain `false`: the current client cannot
safely distinguish nonmembership from bot inaccessibility. Missing parent permissions
remain unknown. There are at most `channelLimit` membership probes, all GET; raw
responses and errors are never exposed. The tool does not infer target membership
from the bot's membership. An archived thread reports sending as false until unarchived; locked
threads require MANAGE_THREADS to unarchive.

Coverage is limited to guild channels and active threads visible to the bot REST
API. Archived/inaccessible threads are not exhaustively listed, and missing entries
do not establish that the target cannot access them. Failed channel discovery is
reported in `limitations`; failed guild/member/role lookups raise a generic error.
Permission lists are computed bitfields, not proof of membership or permission to
perform every action. Role hierarchy, verification requirements, guild rules,
channel type, voice state, and other runtime restrictions may still prevent actions.
`can_send_messages` describes text messages (including voice channel chat), and is
false for category/forum/media containers; forum post creation is not evaluated.

Offline regression checks (no credentials or network needed):

```sh
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

The tests use standard-library unittest, a fake REST client, and minimal import
stubs only when the declared runtime dependencies are unavailable. They do not
exercise the live Discord API or replace a real FastMCP transport integration test.
