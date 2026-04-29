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
