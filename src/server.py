from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from .discord_api import DiscordApiClient, DiscordApiError
from .settings import load_settings

SETTINGS = load_settings()
CLIENT = DiscordApiClient(SETTINGS.token, SETTINGS.api_base_url)

mcp = FastMCP(
    name="Discord Admin MCP",
    instructions=(
        "Tools for Discord administration and moderation operations. "
        "Use the configured default guild when guildId is omitted. "
        "Prefer read operations first and keep write operations narrowly scoped."
    ),
    host=SETTINGS.host,
    port=SETTINGS.port,
    log_level=SETTINGS.log_level,
    streamable_http_path="/mcp",
)

CHANNEL_TYPES = {
    0: "GUILD_TEXT",
    1: "DM",
    2: "GUILD_VOICE",
    3: "GROUP_DM",
    4: "GUILD_CATEGORY",
    5: "GUILD_ANNOUNCEMENT",
    10: "ANNOUNCEMENT_THREAD",
    11: "PUBLIC_THREAD",
    12: "PRIVATE_THREAD",
    13: "GUILD_STAGE_VOICE",
    14: "GUILD_DIRECTORY",
    15: "GUILD_FORUM",
    16: "GUILD_MEDIA",
}

PERMISSION_BITS: dict[str, int] = {
    "CREATE_INSTANT_INVITE": 1 << 0,
    "KICK_MEMBERS": 1 << 1,
    "BAN_MEMBERS": 1 << 2,
    "ADMINISTRATOR": 1 << 3,
    "MANAGE_CHANNELS": 1 << 4,
    "MANAGE_GUILD": 1 << 5,
    "ADD_REACTIONS": 1 << 6,
    "VIEW_AUDIT_LOG": 1 << 7,
    "PRIORITY_SPEAKER": 1 << 8,
    "STREAM": 1 << 9,
    "VIEW_CHANNEL": 1 << 10,
    "SEND_MESSAGES": 1 << 11,
    "SEND_TTS_MESSAGES": 1 << 12,
    "MANAGE_MESSAGES": 1 << 13,
    "EMBED_LINKS": 1 << 14,
    "ATTACH_FILES": 1 << 15,
    "READ_MESSAGE_HISTORY": 1 << 16,
    "MENTION_EVERYONE": 1 << 17,
    "USE_EXTERNAL_EMOJIS": 1 << 18,
    "VIEW_GUILD_INSIGHTS": 1 << 19,
    "CONNECT": 1 << 20,
    "SPEAK": 1 << 21,
    "MUTE_MEMBERS": 1 << 22,
    "DEAFEN_MEMBERS": 1 << 23,
    "MOVE_MEMBERS": 1 << 24,
    "USE_VAD": 1 << 25,
    "CHANGE_NICKNAME": 1 << 26,
    "MANAGE_NICKNAMES": 1 << 27,
    "MANAGE_ROLES": 1 << 28,
    "MANAGE_WEBHOOKS": 1 << 29,
    "MANAGE_GUILD_EXPRESSIONS": 1 << 30,
    "USE_APPLICATION_COMMANDS": 1 << 31,
    "REQUEST_TO_SPEAK": 1 << 32,
    "MANAGE_EVENTS": 1 << 33,
    "MANAGE_THREADS": 1 << 34,
    "CREATE_PUBLIC_THREADS": 1 << 35,
    "CREATE_PRIVATE_THREADS": 1 << 36,
    "USE_EXTERNAL_STICKERS": 1 << 37,
    "SEND_MESSAGES_IN_THREADS": 1 << 38,
    "USE_EMBEDDED_ACTIVITIES": 1 << 39,
    "MODERATE_MEMBERS": 1 << 40,
    "VIEW_CREATOR_MONETIZATION_ANALYTICS": 1 << 41,
    "USE_SOUNDBOARD": 1 << 42,
    "CREATE_GUILD_EXPRESSIONS": 1 << 43,
    "CREATE_EVENTS": 1 << 44,
    "USE_EXTERNAL_SOUNDS": 1 << 45,
    "SEND_VOICE_MESSAGES": 1 << 46,
    "SEND_POLLS": 1 << 49,
    "USE_EXTERNAL_APPS": 1 << 50,
}

PERMISSION_ALIASES = {
    "MESSAGE_SEND": "SEND_MESSAGES",
    "MESSAGE_HISTORY": "READ_MESSAGE_HISTORY",
    "VOICE_CONNECT": "CONNECT",
    "VOICE_SPEAK": "SPEAK",
    "MANAGE_SERVER": "MANAGE_GUILD",
    "MANAGE_EMOJIS_AND_STICKERS": "MANAGE_GUILD_EXPRESSIONS",
    "USE_EXTERNAL_EMOJIS_AND_STICKERS": "USE_EXTERNAL_STICKERS",
}


def _resolve_guild_id(guildId: str | None) -> str:
    resolved = (guildId or "").strip() or SETTINGS.default_guild_id
    if not resolved:
        raise DiscordApiError("guildId is required when DISCORD_GUILD_ID is not set.")
    return resolved


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise DiscordApiError(f"Invalid boolean value: {value}")


def _parse_int(
    value: Any,
    *,
    field: str,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None or value == "":
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise DiscordApiError(f"Invalid integer for {field}: {value}") from exc
    if minimum is not None and parsed < minimum:
        raise DiscordApiError(f"{field} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise DiscordApiError(f"{field} must be <= {maximum}")
    return parsed


def _now_plus_seconds(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _limit(value: Any, *, default: int, maximum: int) -> int:
    parsed = _parse_int(value, field="limit", default=default, minimum=1)
    assert parsed is not None
    return min(parsed, maximum)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _permission_bits_from_names(value: str | None) -> int:
    bits = 0
    for raw_name in _split_csv(value):
        normalized = raw_name.upper().strip()
        normalized = PERMISSION_ALIASES.get(normalized, normalized)
        if normalized not in PERMISSION_BITS:
            raise DiscordApiError(f"Unknown permission name: {raw_name}")
        bits |= PERMISSION_BITS[normalized]
    return bits


def _permission_names_from_bits(raw_value: str | int | None) -> list[str]:
    if raw_value in (None, ""):
        return []
    bits = int(raw_value)
    enabled: list[str] = []
    for name, flag in PERMISSION_BITS.items():
        if bits & flag:
            enabled.append(name)
    return enabled


def _parse_permission_value(raw_value: str | None, named_value: str | None) -> int:
    if raw_value not in (None, ""):
        return int(str(raw_value).strip())
    return _permission_bits_from_names(named_value)


def _normalize_invite_code(inviteCode: str) -> str:
    if not inviteCode:
        raise DiscordApiError("inviteCode cannot be empty")
    code = inviteCode.strip()
    for prefix in (
        "https://discord.gg/",
        "http://discord.gg/",
        "https://discord.com/invite/",
        "http://discord.com/invite/",
    ):
        if code.startswith(prefix):
            return code.removeprefix(prefix)
    return code


def _normalize_emoji_for_route(emoji: str) -> str:
    raw = emoji.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1]
    if raw.startswith("a:"):
        raw = raw[2:]
    elif raw.startswith(":"):
        raw = raw[1:]
    return raw


def _message_link(channel: dict[str, Any], message: dict[str, Any]) -> str | None:
    guild_id = message.get("guild_id") or channel.get("guild_id")
    if not guild_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel['id']}/{message['id']}"


def _serialize_role(role: dict[str, Any]) -> dict[str, Any]:
    color = role.get("color") or 0
    return {
        "id": role["id"],
        "name": role.get("name"),
        "color": color,
        "color_hex": f"#{color:06X}" if color else None,
        "hoist": role.get("hoist", False),
        "mentionable": role.get("mentionable", False),
        "position": role.get("position"),
        "permissions_raw": role.get("permissions", "0"),
        "permissions": _permission_names_from_bits(role.get("permissions", "0")),
    }


def _serialize_channel(channel: dict[str, Any]) -> dict[str, Any]:
    channel_type = channel.get("type")
    return {
        "id": channel["id"],
        "guild_id": channel.get("guild_id"),
        "name": channel.get("name"),
        "type": channel_type,
        "type_name": CHANNEL_TYPES.get(channel_type, f"UNKNOWN_{channel_type}"),
        "parent_id": channel.get("parent_id"),
        "position": channel.get("position"),
        "topic": channel.get("topic"),
        "nsfw": channel.get("nsfw"),
        "rate_limit_per_user": channel.get("rate_limit_per_user"),
        "bitrate": channel.get("bitrate"),
        "user_limit": channel.get("user_limit"),
        "rtc_region": channel.get("rtc_region"),
        "permission_overwrites": channel.get("permission_overwrites", []),
    }


def _serialize_message(message: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message["id"],
        "channel_id": channel["id"],
        "guild_id": message.get("guild_id") or channel.get("guild_id"),
        "author": {
            "id": message.get("author", {}).get("id"),
            "username": message.get("author", {}).get("username"),
            "global_name": message.get("author", {}).get("global_name"),
        },
        "content": message.get("content"),
        "timestamp": message.get("timestamp"),
        "edited_timestamp": message.get("edited_timestamp"),
        "attachments": [
            {
                "id": attachment["id"],
                "filename": attachment.get("filename"),
                "content_type": attachment.get("content_type"),
                "size": attachment.get("size"),
                "url": attachment.get("url"),
                "proxy_url": attachment.get("proxy_url"),
            }
            for attachment in message.get("attachments", [])
        ],
        "jump_url": _message_link(channel, message),
    }


def _serialize_invite(invite: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": invite["code"],
        "url": f"https://discord.gg/{invite['code']}",
        "channel": invite.get("channel"),
        "guild": invite.get("guild"),
        "inviter": invite.get("inviter"),
        "uses": invite.get("uses"),
        "max_uses": invite.get("max_uses"),
        "max_age": invite.get("max_age"),
        "temporary": invite.get("temporary"),
        "expires_at": invite.get("expires_at"),
        "approximate_member_count": invite.get("approximate_member_count"),
        "approximate_presence_count": invite.get("approximate_presence_count"),
    }


def _serialize_webhook(webhook: dict[str, Any]) -> dict[str, Any]:
    token = webhook.get("token")
    url = None
    if token:
        url = f"https://discord.com/api/webhooks/{webhook['id']}/{token}"
    return {
        "id": webhook["id"],
        "name": webhook.get("name"),
        "channel_id": webhook.get("channel_id"),
        "guild_id": webhook.get("guild_id"),
        "application_id": webhook.get("application_id"),
        "url": url,
    }


def _serialize_emoji(emoji: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": emoji["id"],
        "name": emoji.get("name"),
        "roles": emoji.get("roles", []),
        "require_colons": emoji.get("require_colons"),
        "managed": emoji.get("managed"),
        "animated": emoji.get("animated"),
        "available": emoji.get("available"),
    }


def _serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event["id"],
        "guild_id": event.get("guild_id"),
        "channel_id": event.get("channel_id"),
        "name": event.get("name"),
        "description": event.get("description"),
        "scheduled_start_time": event.get("scheduled_start_time"),
        "scheduled_end_time": event.get("scheduled_end_time"),
        "privacy_level": event.get("privacy_level"),
        "status": event.get("status"),
        "entity_type": event.get("entity_type"),
        "entity_id": event.get("entity_id"),
        "entity_metadata": event.get("entity_metadata"),
        "user_count": event.get("user_count"),
    }


def _get_guild(guildId: str | None) -> dict[str, Any]:
    guild_id = _resolve_guild_id(guildId)
    return CLIENT.request("GET", f"/guilds/{guild_id}", params={"with_counts": "true"})


def _get_roles(guild_id: str) -> list[dict[str, Any]]:
    return CLIENT.request("GET", f"/guilds/{guild_id}/roles")


def _get_channels(guild_id: str) -> list[dict[str, Any]]:
    channels = CLIENT.request("GET", f"/guilds/{guild_id}/channels")
    for channel in channels:
        channel.setdefault("guild_id", guild_id)
    return sorted(channels, key=lambda item: (item.get("position", 0), item.get("name", "")))


def _get_channel(channelId: str) -> dict[str, Any]:
    if not channelId:
        raise DiscordApiError("channelId cannot be empty")
    return CLIENT.request("GET", f"/channels/{channelId}")


def _get_message(channelId: str, messageId: str) -> tuple[dict[str, Any], dict[str, Any]]:
    channel = _get_channel(channelId)
    message = CLIENT.request("GET", f"/channels/{channelId}/messages/{messageId}")
    return channel, message


def _get_role(guild_id: str, roleId: str) -> dict[str, Any]:
    for role in _get_roles(guild_id):
        if role["id"] == roleId:
            return role
    raise DiscordApiError(f"Role not found by roleId: {roleId}")


def _get_member(guild_id: str, userId: str) -> dict[str, Any]:
    return CLIENT.request("GET", f"/guilds/{guild_id}/members/{userId}")


def _ensure_dm_channel(userId: str) -> dict[str, Any]:
    if not userId:
        raise DiscordApiError("userId cannot be empty")
    return CLIENT.request("POST", "/users/@me/channels", json={"recipient_id": userId})


@mcp.tool()
def healthcheck() -> dict[str, Any]:
    """Return server, token, and default guild readiness status."""
    me = CLIENT.request("GET", "/users/@me")
    default_guild: dict[str, Any] | None = None
    if SETTINGS.default_guild_id:
        default_guild = CLIENT.request(
            "GET",
            f"/guilds/{SETTINGS.default_guild_id}",
            params={"with_counts": "true"},
        )
    return {
        "ok": True,
        "server": "discord-admin-mcp",
        "transport": "streamable-http",
        "endpoint_path": "/mcp",
        "bot_user": {
            "id": me.get("id"),
            "username": me.get("username"),
            "global_name": me.get("global_name"),
        },
        "default_guild_id": SETTINGS.default_guild_id or None,
        "default_guild_name": default_guild.get("name") if default_guild else None,
        "credentials_present": True,
        "discord_token": SETTINGS.masked_token,
    }


@mcp.tool(name="get_server_info")
def get_server_info(guildId: str | None = None) -> dict[str, Any]:
    """Get detailed Discord server information."""
    guild = _get_guild(guildId)
    guild_id = guild["id"]
    roles = _get_roles(guild_id)
    channels = _get_channels(guild_id)
    return {
        "ok": True,
        "guild": {
            "id": guild_id,
            "name": guild.get("name"),
            "description": guild.get("description"),
            "owner_id": guild.get("owner_id"),
            "preferred_locale": guild.get("preferred_locale"),
            "verification_level": guild.get("verification_level"),
            "nsfw_level": guild.get("nsfw_level"),
            "premium_tier": guild.get("premium_tier"),
            "member_count": guild.get("approximate_member_count"),
            "presence_count": guild.get("approximate_presence_count"),
        },
        "role_count": len(roles),
        "channel_count": len(channels),
    }


@mcp.tool(name="list_channels")
def list_channels(guildId: str | None = None) -> dict[str, Any]:
    """List all channels in a guild."""
    guild_id = _resolve_guild_id(guildId)
    channels = _get_channels(guild_id)
    return {"ok": True, "guild_id": guild_id, "channels": [_serialize_channel(c) for c in channels]}


@mcp.tool(name="find_channel")
def find_channel(guildId: str | None = None, channelName: str = "") -> dict[str, Any]:
    """Find channels by case-insensitive name."""
    if not channelName.strip():
        raise DiscordApiError("channelName cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    matches = [
        _serialize_channel(channel)
        for channel in _get_channels(guild_id)
        if (channel.get("name") or "").lower() == channelName.strip().lower()
    ]
    return {"ok": True, "guild_id": guild_id, "query": channelName, "matches": matches}


@mcp.tool(name="get_channel_info")
def get_channel_info(guildId: str | None = None, channelId: str = "") -> dict[str, Any]:
    """Get detailed information about a channel."""
    channel = _get_channel(channelId)
    resolved_guild_id = channel.get("guild_id") or _resolve_guild_id(guildId)
    return {"ok": True, "guild_id": resolved_guild_id, "channel": _serialize_channel(channel)}


@mcp.tool(name="create_text_channel")
def create_text_channel(
    guildId: str | None = None,
    name: str = "",
    categoryId: str | None = None,
    topic: str | None = None,
    nsfw: str | None = None,
    slowmode: str | None = None,
    position: str | None = None,
) -> dict[str, Any]:
    """Create a text channel."""
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    payload: dict[str, Any] = {"name": name, "type": 0}
    if categoryId:
        payload["parent_id"] = categoryId
    if topic:
        payload["topic"] = topic
    if nsfw not in (None, ""):
        payload["nsfw"] = _parse_bool(nsfw)
    if slowmode not in (None, ""):
        payload["rate_limit_per_user"] = _parse_int(
            slowmode, field="slowmode", minimum=0, maximum=21600
        )
    if position not in (None, ""):
        payload["position"] = _parse_int(position, field="position", minimum=0)
    channel = CLIENT.request("POST", f"/guilds/{guild_id}/channels", json=payload)
    return {"ok": True, "guild_id": guild_id, "channel": _serialize_channel(channel)}


@mcp.tool(name="edit_text_channel")
def edit_text_channel(
    guildId: str | None = None,
    channelId: str = "",
    name: str | None = None,
    topic: str | None = None,
    nsfw: str | None = None,
    slowmode: str | None = None,
    categoryId: str | None = None,
    position: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Edit a text channel."""
    payload: dict[str, Any] = {}
    if name not in (None, ""):
        payload["name"] = name
    if topic is not None:
        payload["topic"] = topic
    if nsfw not in (None, ""):
        payload["nsfw"] = _parse_bool(nsfw)
    if slowmode not in (None, ""):
        payload["rate_limit_per_user"] = _parse_int(
            slowmode, field="slowmode", minimum=0, maximum=21600
        )
    if categoryId is not None:
        payload["parent_id"] = categoryId or None
    if position not in (None, ""):
        payload["position"] = _parse_int(position, field="position", minimum=0)
    if not payload:
        raise DiscordApiError("No changes provided.")
    channel = CLIENT.request(
        "PATCH",
        f"/channels/{channelId}",
        json=payload,
        headers=CLIENT.audit_headers(reason),
    )
    resolved_guild_id = channel.get("guild_id") or _resolve_guild_id(guildId)
    return {"ok": True, "guild_id": resolved_guild_id, "channel": _serialize_channel(channel)}


@mcp.tool(name="move_channel")
def move_channel(
    guildId: str | None = None,
    channelId: str = "",
    categoryId: str | None = None,
    position: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Move a channel to another category and/or change position."""
    return edit_text_channel(
        guildId=guildId,
        channelId=channelId,
        categoryId=categoryId,
        position=position,
        reason=reason,
    )


@mcp.tool(name="delete_channel")
def delete_channel(
    guildId: str | None = None,
    channelId: str = "",
    reason: str | None = None,
) -> dict[str, Any]:
    """Delete a channel."""
    channel = _get_channel(channelId)
    CLIENT.request(
        "DELETE",
        f"/channels/{channelId}",
        headers=CLIENT.audit_headers(reason),
    )
    resolved_guild_id = channel.get("guild_id") or _resolve_guild_id(guildId)
    return {
        "ok": True,
        "guild_id": resolved_guild_id,
        "deleted_channel": _serialize_channel(channel),
    }


@mcp.tool(name="create_category")
def create_category(guildId: str | None = None, name: str = "") -> dict[str, Any]:
    """Create a category."""
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    channel = CLIENT.request(
        "POST",
        f"/guilds/{guild_id}/channels",
        json={"name": name, "type": 4},
    )
    return {"ok": True, "guild_id": guild_id, "category": _serialize_channel(channel)}


@mcp.tool(name="delete_category")
def delete_category(
    guildId: str | None = None,
    categoryId: str = "",
) -> dict[str, Any]:
    """Delete a category."""
    channel = _get_channel(categoryId)
    if channel.get("type") != 4:
        raise DiscordApiError("categoryId does not refer to a category channel.")
    CLIENT.request("DELETE", f"/channels/{categoryId}")
    resolved_guild_id = channel.get("guild_id") or _resolve_guild_id(guildId)
    return {"ok": True, "guild_id": resolved_guild_id, "deleted_category": _serialize_channel(channel)}


@mcp.tool(name="find_category")
def find_category(guildId: str | None = None, categoryName: str = "") -> dict[str, Any]:
    """Find categories by case-insensitive name."""
    if not categoryName.strip():
        raise DiscordApiError("categoryName cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    matches = [
        _serialize_channel(channel)
        for channel in _get_channels(guild_id)
        if channel.get("type") == 4
        and (channel.get("name") or "").lower() == categoryName.strip().lower()
    ]
    return {"ok": True, "guild_id": guild_id, "query": categoryName, "matches": matches}


@mcp.tool(name="list_channels_in_category")
def list_channels_in_category(
    guildId: str | None = None,
    categoryId: str = "",
) -> dict[str, Any]:
    """List channels in a category."""
    guild_id = _resolve_guild_id(guildId)
    channels = [
        _serialize_channel(channel)
        for channel in _get_channels(guild_id)
        if channel.get("parent_id") == categoryId
    ]
    return {"ok": True, "guild_id": guild_id, "category_id": categoryId, "channels": channels}


@mcp.tool(name="list_channel_permission_overwrites")
def list_channel_permission_overwrites(
    guildId: str | None = None,
    channelId: str = "",
) -> dict[str, Any]:
    """List permission overwrites for a channel."""
    channel = _get_channel(channelId)
    resolved_guild_id = channel.get("guild_id") or _resolve_guild_id(guildId)
    roles = {role["id"]: role for role in _get_roles(resolved_guild_id)}
    overwrites: list[dict[str, Any]] = []
    for overwrite in channel.get("permission_overwrites", []):
        overwrite_type = overwrite.get("type")
        target_id = overwrite.get("id")
        target: dict[str, Any] | None = None
        if overwrite_type == 0:
            role = roles.get(target_id)
            target = {"id": target_id, "type": "role", "name": role.get("name") if role else None}
        elif overwrite_type == 1:
            try:
                member = _get_member(resolved_guild_id, target_id)
                user = member.get("user", {})
                target = {
                    "id": target_id,
                    "type": "member",
                    "username": user.get("username"),
                    "global_name": user.get("global_name"),
                    "nick": member.get("nick"),
                }
            except DiscordApiError:
                target = {"id": target_id, "type": "member"}
        overwrites.append(
            {
                "id": target_id,
                "type": "role" if overwrite_type == 0 else "member",
                "allow_raw": overwrite.get("allow", "0"),
                "deny_raw": overwrite.get("deny", "0"),
                "allow_permissions": _permission_names_from_bits(overwrite.get("allow", "0")),
                "deny_permissions": _permission_names_from_bits(overwrite.get("deny", "0")),
                "target": target,
            }
        )
    return {"ok": True, "guild_id": resolved_guild_id, "channel_id": channelId, "overwrites": overwrites}


def _upsert_channel_permission_overwrite(
    *,
    guildId: str | None,
    channelId: str,
    targetType: int,
    targetId: str,
    allowRaw: str | None,
    denyRaw: str | None,
    allowPermissions: str | None,
    denyPermissions: str | None,
    reason: str | None,
) -> dict[str, Any]:
    if not targetId:
        raise DiscordApiError("targetId cannot be empty")
    channel = _get_channel(channelId)
    resolved_guild_id = channel.get("guild_id") or _resolve_guild_id(guildId)
    allow = _parse_permission_value(allowRaw, allowPermissions)
    deny = _parse_permission_value(denyRaw, denyPermissions)
    CLIENT.request(
        "PUT",
        f"/channels/{channelId}/permissions/{targetId}",
        json={"allow": str(allow), "deny": str(deny), "type": targetType},
        headers=CLIENT.audit_headers(reason),
    )
    return {
        "ok": True,
        "guild_id": resolved_guild_id,
        "channel_id": channelId,
        "target_id": targetId,
        "target_type": "role" if targetType == 0 else "member",
        "allow_raw": str(allow),
        "deny_raw": str(deny),
        "allow_permissions": _permission_names_from_bits(allow),
        "deny_permissions": _permission_names_from_bits(deny),
    }


@mcp.tool(name="upsert_role_channel_permissions")
def upsert_role_channel_permissions(
    guildId: str | None = None,
    channelId: str = "",
    roleId: str = "",
    allowRaw: str | None = None,
    denyRaw: str | None = None,
    allowPermissions: str | None = None,
    denyPermissions: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Create or update a role permission overwrite on a channel."""
    return _upsert_channel_permission_overwrite(
        guildId=guildId,
        channelId=channelId,
        targetType=0,
        targetId=roleId,
        allowRaw=allowRaw,
        denyRaw=denyRaw,
        allowPermissions=allowPermissions,
        denyPermissions=denyPermissions,
        reason=reason,
    )


@mcp.tool(name="upsert_member_channel_permissions")
def upsert_member_channel_permissions(
    guildId: str | None = None,
    channelId: str = "",
    userId: str = "",
    allowRaw: str | None = None,
    denyRaw: str | None = None,
    allowPermissions: str | None = None,
    denyPermissions: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Create or update a member permission overwrite on a channel."""
    return _upsert_channel_permission_overwrite(
        guildId=guildId,
        channelId=channelId,
        targetType=1,
        targetId=userId,
        allowRaw=allowRaw,
        denyRaw=denyRaw,
        allowPermissions=allowPermissions,
        denyPermissions=denyPermissions,
        reason=reason,
    )


@mcp.tool(name="delete_channel_permission_overwrite")
def delete_channel_permission_overwrite(
    guildId: str | None = None,
    channelId: str = "",
    targetType: str = "",
    targetId: str = "",
    reason: str | None = None,
) -> dict[str, Any]:
    """Delete a permission overwrite from a channel."""
    channel = _get_channel(channelId)
    resolved_guild_id = channel.get("guild_id") or _resolve_guild_id(guildId)
    normalized = targetType.strip().lower()
    if normalized not in {"role", "member"}:
        raise DiscordApiError("targetType must be 'role' or 'member'.")
    CLIENT.request(
        "DELETE",
        f"/channels/{channelId}/permissions/{targetId}",
        headers=CLIENT.audit_headers(reason),
    )
    return {
        "ok": True,
        "guild_id": resolved_guild_id,
        "channel_id": channelId,
        "target_id": targetId,
        "target_type": normalized,
    }


@mcp.tool(name="send_message")
def send_message(channelId: str = "", message: str = "") -> dict[str, Any]:
    """Send a message to a channel."""
    if not message:
        raise DiscordApiError("message cannot be empty")
    channel = _get_channel(channelId)
    sent = CLIENT.request(
        "POST",
        f"/channels/{channelId}/messages",
        json={"content": message},
    )
    return {"ok": True, "message": _serialize_message(sent, channel)}


@mcp.tool(name="edit_message")
def edit_message(channelId: str = "", messageId: str = "", newMessage: str = "") -> dict[str, Any]:
    """Edit a channel message."""
    if not newMessage:
        raise DiscordApiError("newMessage cannot be empty")
    channel = _get_channel(channelId)
    updated = CLIENT.request(
        "PATCH",
        f"/channels/{channelId}/messages/{messageId}",
        json={"content": newMessage},
    )
    return {"ok": True, "message": _serialize_message(updated, channel)}


@mcp.tool(name="delete_message")
def delete_message(channelId: str = "", messageId: str = "") -> dict[str, Any]:
    """Delete a channel message."""
    channel, message = _get_message(channelId, messageId)
    CLIENT.request("DELETE", f"/channels/{channelId}/messages/{messageId}")
    return {"ok": True, "deleted_message": _serialize_message(message, channel)}


@mcp.tool(name="read_messages")
def read_messages(channelId: str = "", count: str | None = None) -> dict[str, Any]:
    """Read recent messages from a channel."""
    channel = _get_channel(channelId)
    limit = _limit(count, default=25, maximum=100)
    messages = CLIENT.request("GET", f"/channels/{channelId}/messages", params={"limit": limit})
    return {
        "ok": True,
        "channel": _serialize_channel(channel),
        "messages": [_serialize_message(item, channel) for item in messages],
    }


@mcp.tool(name="add_reaction")
def add_reaction(channelId: str = "", messageId: str = "", emoji: str = "") -> dict[str, Any]:
    """Add a reaction to a message."""
    channel, message = _get_message(channelId, messageId)
    emoji_route = _normalize_emoji_for_route(emoji)
    CLIENT.request(
        "PUT",
        f"/channels/{channelId}/messages/{messageId}/reactions/{emoji_route}/@me",
    )
    return {
        "ok": True,
        "channel_id": channelId,
        "message_id": messageId,
        "emoji": emoji,
        "jump_url": _message_link(channel, message),
    }


@mcp.tool(name="remove_reaction")
def remove_reaction(channelId: str = "", messageId: str = "", emoji: str = "") -> dict[str, Any]:
    """Remove the bot's reaction from a message."""
    channel, message = _get_message(channelId, messageId)
    emoji_route = _normalize_emoji_for_route(emoji)
    CLIENT.request(
        "DELETE",
        f"/channels/{channelId}/messages/{messageId}/reactions/{emoji_route}/@me",
    )
    return {
        "ok": True,
        "channel_id": channelId,
        "message_id": messageId,
        "emoji": emoji,
        "jump_url": _message_link(channel, message),
    }


@mcp.tool(name="get_attachment")
def get_attachment(
    channelId: str = "",
    messageId: str = "",
    attachmentId: str | None = None,
) -> dict[str, Any]:
    """Get attachment metadata from a message."""
    _channel, message = _get_message(channelId, messageId)
    attachments = [
        {
            "id": attachment["id"],
            "filename": attachment.get("filename"),
            "content_type": attachment.get("content_type"),
            "size": attachment.get("size"),
            "url": attachment.get("url"),
            "proxy_url": attachment.get("proxy_url"),
        }
        for attachment in message.get("attachments", [])
    ]
    if attachmentId:
        attachments = [item for item in attachments if item["id"] == attachmentId]
    return {"ok": True, "channel_id": channelId, "message_id": messageId, "attachments": attachments}


@mcp.tool(name="get_user_id_by_name")
def get_user_id_by_name(username: str = "", guildId: str | None = None) -> dict[str, Any]:
    """Find a user ID by username, global name, nickname, or username#discriminator."""
    if not username.strip():
        raise DiscordApiError("username cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    query = username.split("#", 1)[0].strip()
    members = CLIENT.request(
        "GET",
        f"/guilds/{guild_id}/members/search",
        params={"query": query, "limit": 25},
    )

    def score(member: dict[str, Any]) -> tuple[int, str]:
        user = member.get("user", {})
        variants = [
            user.get("username", ""),
            user.get("global_name", "") or "",
            member.get("nick", "") or "",
            f"{user.get('username', '')}#{user.get('discriminator', '')}",
        ]
        exact = any(item.lower() == username.lower() for item in variants if item)
        return (0 if exact else 1, user.get("username", ""))

    sorted_members = sorted(members, key=score)
    matches = [
        {
            "id": member.get("user", {}).get("id"),
            "username": member.get("user", {}).get("username"),
            "global_name": member.get("user", {}).get("global_name"),
            "nick": member.get("nick"),
        }
        for member in sorted_members
    ]
    return {"ok": True, "guild_id": guild_id, "query": username, "matches": matches}


@mcp.tool(name="send_private_message")
def send_private_message(userId: str = "", message: str = "") -> dict[str, Any]:
    """Send a direct message to a user."""
    if not message:
        raise DiscordApiError("message cannot be empty")
    channel = _ensure_dm_channel(userId)
    sent = CLIENT.request(
        "POST",
        f"/channels/{channel['id']}/messages",
        json={"content": message},
    )
    return {"ok": True, "dm_channel_id": channel["id"], "message": _serialize_message(sent, channel)}


@mcp.tool(name="edit_private_message")
def edit_private_message(userId: str = "", messageId: str = "", newMessage: str = "") -> dict[str, Any]:
    """Edit a direct message sent by the bot."""
    channel = _ensure_dm_channel(userId)
    updated = CLIENT.request(
        "PATCH",
        f"/channels/{channel['id']}/messages/{messageId}",
        json={"content": newMessage},
    )
    return {"ok": True, "dm_channel_id": channel["id"], "message": _serialize_message(updated, channel)}


@mcp.tool(name="delete_private_message")
def delete_private_message(userId: str = "", messageId: str = "") -> dict[str, Any]:
    """Delete a direct message from the bot DM thread."""
    channel = _ensure_dm_channel(userId)
    message = CLIENT.request("GET", f"/channels/{channel['id']}/messages/{messageId}")
    CLIENT.request("DELETE", f"/channels/{channel['id']}/messages/{messageId}")
    return {"ok": True, "dm_channel_id": channel["id"], "deleted_message": _serialize_message(message, channel)}


@mcp.tool(name="read_private_messages")
def read_private_messages(userId: str = "", count: str | None = None) -> dict[str, Any]:
    """Read recent direct messages from a user thread."""
    channel = _ensure_dm_channel(userId)
    limit = _limit(count, default=25, maximum=100)
    messages = CLIENT.request("GET", f"/channels/{channel['id']}/messages", params={"limit": limit})
    return {
        "ok": True,
        "dm_channel_id": channel["id"],
        "messages": [_serialize_message(item, channel) for item in messages],
    }


@mcp.tool(name="list_roles")
def list_roles(guildId: str | None = None) -> dict[str, Any]:
    """List roles in a guild."""
    guild_id = _resolve_guild_id(guildId)
    roles = _get_roles(guild_id)
    roles.sort(key=lambda role: role.get("position", 0), reverse=True)
    return {"ok": True, "guild_id": guild_id, "roles": [_serialize_role(role) for role in roles]}


@mcp.tool(name="create_role")
def create_role(
    guildId: str | None = None,
    name: str = "",
    color: str | None = None,
    hoist: str | None = None,
    mentionable: str | None = None,
    permissions: str | None = None,
) -> dict[str, Any]:
    """Create a role."""
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    payload: dict[str, Any] = {"name": name}
    if color not in (None, ""):
        payload["color"] = _parse_int(color, field="color", minimum=0)
    if hoist not in (None, ""):
        payload["hoist"] = _parse_bool(hoist)
    if mentionable not in (None, ""):
        payload["mentionable"] = _parse_bool(mentionable)
    if permissions not in (None, ""):
        payload["permissions"] = str(int(permissions))
    role = CLIENT.request("POST", f"/guilds/{guild_id}/roles", json=payload)
    return {"ok": True, "guild_id": guild_id, "role": _serialize_role(role)}


@mcp.tool(name="edit_role")
def edit_role(
    guildId: str | None = None,
    roleId: str = "",
    name: str | None = None,
    color: str | None = None,
    hoist: str | None = None,
    mentionable: str | None = None,
    permissions: str | None = None,
) -> dict[str, Any]:
    """Edit a role."""
    guild_id = _resolve_guild_id(guildId)
    if roleId == guild_id:
        raise DiscordApiError("Cannot edit the @everyone role directly.")
    payload: dict[str, Any] = {}
    if name not in (None, ""):
        payload["name"] = name
    if color is not None:
        payload["color"] = _parse_int(color, field="color", minimum=0) if color else 0
    if hoist not in (None, ""):
        payload["hoist"] = _parse_bool(hoist)
    if mentionable not in (None, ""):
        payload["mentionable"] = _parse_bool(mentionable)
    if permissions not in (None, ""):
        payload["permissions"] = str(int(permissions))
    if not payload:
        raise DiscordApiError("No changes provided.")
    role = CLIENT.request("PATCH", f"/guilds/{guild_id}/roles/{roleId}", json=payload)
    return {"ok": True, "guild_id": guild_id, "role": _serialize_role(role)}


@mcp.tool(name="delete_role")
def delete_role(guildId: str | None = None, roleId: str = "") -> dict[str, Any]:
    """Delete a role."""
    guild_id = _resolve_guild_id(guildId)
    if roleId == guild_id:
        raise DiscordApiError("Cannot delete the @everyone role.")
    role = _get_role(guild_id, roleId)
    CLIENT.request("DELETE", f"/guilds/{guild_id}/roles/{roleId}")
    return {"ok": True, "guild_id": guild_id, "deleted_role": _serialize_role(role)}


@mcp.tool(name="assign_role")
def assign_role(guildId: str | None = None, userId: str = "", roleId: str = "") -> dict[str, Any]:
    """Assign a role to a member."""
    guild_id = _resolve_guild_id(guildId)
    role = _get_role(guild_id, roleId)
    member = _get_member(guild_id, userId)
    CLIENT.request("PUT", f"/guilds/{guild_id}/members/{userId}/roles/{roleId}")
    return {
        "ok": True,
        "guild_id": guild_id,
        "user_id": userId,
        "role": _serialize_role(role),
        "nick": member.get("nick"),
    }


@mcp.tool(name="remove_role")
def remove_role(guildId: str | None = None, userId: str = "", roleId: str = "") -> dict[str, Any]:
    """Remove a role from a member."""
    guild_id = _resolve_guild_id(guildId)
    role = _get_role(guild_id, roleId)
    CLIENT.request("DELETE", f"/guilds/{guild_id}/members/{userId}/roles/{roleId}")
    return {"ok": True, "guild_id": guild_id, "user_id": userId, "role": _serialize_role(role)}


@mcp.tool(name="kick_member")
def kick_member(
    guildId: str | None = None,
    userId: str = "",
    reason: str | None = None,
) -> dict[str, Any]:
    """Kick a member from the guild."""
    guild_id = _resolve_guild_id(guildId)
    member = _get_member(guild_id, userId)
    CLIENT.request(
        "DELETE",
        f"/guilds/{guild_id}/members/{userId}",
        headers=CLIENT.audit_headers(reason),
    )
    return {"ok": True, "guild_id": guild_id, "kicked_user": member.get("user"), "reason": reason}


@mcp.tool(name="ban_member")
def ban_member(
    guildId: str | None = None,
    userId: str = "",
    deleteMessageSeconds: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Ban a user from the guild."""
    guild_id = _resolve_guild_id(guildId)
    delete_seconds = _parse_int(
        deleteMessageSeconds,
        field="deleteMessageSeconds",
        default=0,
        minimum=0,
        maximum=604800,
    )
    CLIENT.request(
        "PUT",
        f"/guilds/{guild_id}/bans/{userId}",
        json={"delete_message_seconds": delete_seconds},
        headers=CLIENT.audit_headers(reason),
    )
    return {
        "ok": True,
        "guild_id": guild_id,
        "user_id": userId,
        "delete_message_seconds": delete_seconds,
        "reason": reason,
    }


@mcp.tool(name="unban_member")
def unban_member(
    guildId: str | None = None,
    userId: str = "",
    reason: str | None = None,
) -> dict[str, Any]:
    """Remove a ban from a user."""
    guild_id = _resolve_guild_id(guildId)
    CLIENT.request(
        "DELETE",
        f"/guilds/{guild_id}/bans/{userId}",
        headers=CLIENT.audit_headers(reason),
    )
    return {"ok": True, "guild_id": guild_id, "user_id": userId, "reason": reason}


@mcp.tool(name="timeout_member")
def timeout_member(
    guildId: str | None = None,
    userId: str = "",
    durationSeconds: str = "",
    reason: str | None = None,
) -> dict[str, Any]:
    """Timeout a member for a duration in seconds."""
    guild_id = _resolve_guild_id(guildId)
    duration = _parse_int(
        durationSeconds,
        field="durationSeconds",
        minimum=1,
        maximum=2419200,
    )
    assert duration is not None
    member = CLIENT.request(
        "PATCH",
        f"/guilds/{guild_id}/members/{userId}",
        json={"communication_disabled_until": _now_plus_seconds(duration)},
        headers=CLIENT.audit_headers(reason),
    )
    return {"ok": True, "guild_id": guild_id, "member": member, "duration_seconds": duration}


@mcp.tool(name="remove_timeout")
def remove_timeout(
    guildId: str | None = None,
    userId: str = "",
    reason: str | None = None,
) -> dict[str, Any]:
    """Remove a member timeout."""
    guild_id = _resolve_guild_id(guildId)
    member = CLIENT.request(
        "PATCH",
        f"/guilds/{guild_id}/members/{userId}",
        json={"communication_disabled_until": None},
        headers=CLIENT.audit_headers(reason),
    )
    return {"ok": True, "guild_id": guild_id, "member": member, "reason": reason}


@mcp.tool(name="set_nickname")
def set_nickname(
    guildId: str | None = None,
    userId: str = "",
    nick: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Set or clear a member nickname."""
    guild_id = _resolve_guild_id(guildId)
    member = CLIENT.request(
        "PATCH",
        f"/guilds/{guild_id}/members/{userId}",
        json={"nick": nick or None},
        headers=CLIENT.audit_headers(reason),
    )
    return {"ok": True, "guild_id": guild_id, "member": member, "reason": reason}


@mcp.tool(name="get_bans")
def get_bans(guildId: str | None = None, limit: str | None = None) -> dict[str, Any]:
    """List bans on a guild."""
    guild_id = _resolve_guild_id(guildId)
    max_results = _limit(limit, default=50, maximum=1000)
    bans = CLIENT.request("GET", f"/guilds/{guild_id}/bans", params={"limit": max_results})
    return {"ok": True, "guild_id": guild_id, "bans": bans}


@mcp.tool(name="list_active_threads")
def list_active_threads(guildId: str | None = None) -> dict[str, Any]:
    """List active threads in a guild."""
    guild_id = _resolve_guild_id(guildId)
    payload = CLIENT.request("GET", f"/guilds/{guild_id}/threads/active")
    return {
        "ok": True,
        "guild_id": guild_id,
        "threads": [_serialize_channel(thread) for thread in payload.get("threads", [])],
        "members": payload.get("members", []),
    }


@mcp.tool(name="create_voice_channel")
def create_voice_channel(
    guildId: str | None = None,
    name: str = "",
    categoryId: str | None = None,
    userLimit: str | None = None,
    bitrate: str | None = None,
) -> dict[str, Any]:
    """Create a voice channel."""
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    payload: dict[str, Any] = {"name": name, "type": 2}
    if categoryId:
        payload["parent_id"] = categoryId
    if userLimit not in (None, ""):
        payload["user_limit"] = _parse_int(userLimit, field="userLimit", minimum=0, maximum=99)
    if bitrate not in (None, ""):
        payload["bitrate"] = _parse_int(bitrate, field="bitrate", minimum=8000)
    channel = CLIENT.request("POST", f"/guilds/{guild_id}/channels", json=payload)
    return {"ok": True, "guild_id": guild_id, "channel": _serialize_channel(channel)}


@mcp.tool(name="create_stage_channel")
def create_stage_channel(
    guildId: str | None = None,
    name: str = "",
    categoryId: str | None = None,
    bitrate: str | None = None,
) -> dict[str, Any]:
    """Create a stage channel."""
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    payload: dict[str, Any] = {"name": name, "type": 13}
    if categoryId:
        payload["parent_id"] = categoryId
    if bitrate not in (None, ""):
        payload["bitrate"] = _parse_int(bitrate, field="bitrate", minimum=8000)
    channel = CLIENT.request("POST", f"/guilds/{guild_id}/channels", json=payload)
    return {"ok": True, "guild_id": guild_id, "channel": _serialize_channel(channel)}


@mcp.tool(name="edit_voice_channel")
def edit_voice_channel(
    channelId: str = "",
    name: str | None = None,
    bitrate: str | None = None,
    userLimit: str | None = None,
    rtcRegion: str | None = None,
) -> dict[str, Any]:
    """Edit a voice or stage channel."""
    payload: dict[str, Any] = {}
    if name not in (None, ""):
        payload["name"] = name
    if bitrate not in (None, ""):
        payload["bitrate"] = _parse_int(bitrate, field="bitrate", minimum=8000)
    if userLimit not in (None, ""):
        payload["user_limit"] = _parse_int(userLimit, field="userLimit", minimum=0, maximum=99)
    if rtcRegion is not None:
        payload["rtc_region"] = rtcRegion or None
    if not payload:
        raise DiscordApiError("No changes provided.")
    channel = CLIENT.request("PATCH", f"/channels/{channelId}", json=payload)
    return {"ok": True, "guild_id": channel.get("guild_id"), "channel": _serialize_channel(channel)}


@mcp.tool(name="move_member")
def move_member(guildId: str | None = None, userId: str = "", channelId: str = "") -> dict[str, Any]:
    """Move a member to another voice channel."""
    guild_id = _resolve_guild_id(guildId)
    member = CLIENT.request(
        "PATCH",
        f"/guilds/{guild_id}/members/{userId}",
        json={"channel_id": channelId},
    )
    return {"ok": True, "guild_id": guild_id, "member": member, "channel_id": channelId}


@mcp.tool(name="disconnect_member")
def disconnect_member(guildId: str | None = None, userId: str = "") -> dict[str, Any]:
    """Disconnect a member from voice."""
    guild_id = _resolve_guild_id(guildId)
    member = CLIENT.request(
        "PATCH",
        f"/guilds/{guild_id}/members/{userId}",
        json={"channel_id": None},
    )
    return {"ok": True, "guild_id": guild_id, "member": member}


@mcp.tool(name="modify_voice_state")
def modify_voice_state(
    guildId: str | None = None,
    userId: str = "",
    mute: str | None = None,
    deafen: str | None = None,
) -> dict[str, Any]:
    """Server mute or deafen a member."""
    guild_id = _resolve_guild_id(guildId)
    payload: dict[str, Any] = {}
    if mute not in (None, ""):
        payload["mute"] = _parse_bool(mute)
    if deafen not in (None, ""):
        payload["deaf"] = _parse_bool(deafen)
    if not payload:
        raise DiscordApiError("No changes provided.")
    member = CLIENT.request("PATCH", f"/guilds/{guild_id}/members/{userId}", json=payload)
    return {"ok": True, "guild_id": guild_id, "member": member}


@mcp.tool(name="create_guild_scheduled_event")
def create_guild_scheduled_event(
    guildId: str | None = None,
    name: str = "",
    description: str | None = None,
    scheduledStartTime: str = "",
    scheduledEndTime: str | None = None,
    entityType: str = "",
    channelId: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Create a scheduled event."""
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    if not scheduledStartTime:
        raise DiscordApiError("scheduledStartTime cannot be empty")
    guild_id = _resolve_guild_id(guildId)
    entity_type = _parse_int(entityType, field="entityType", minimum=1, maximum=3)
    assert entity_type is not None
    payload: dict[str, Any] = {
        "name": name,
        "scheduled_start_time": scheduledStartTime,
        "entity_type": entity_type,
        "privacy_level": 2,
    }
    if description:
        payload["description"] = description
    if scheduledEndTime:
        payload["scheduled_end_time"] = scheduledEndTime
    if entity_type in {1, 2}:
        if not channelId:
            raise DiscordApiError("channelId is required for stage and voice events.")
        payload["channel_id"] = channelId
    if entity_type == 3:
        if not location:
            raise DiscordApiError("location is required for external events.")
        payload["entity_metadata"] = {"location": location}
    event = CLIENT.request("POST", f"/guilds/{guild_id}/scheduled-events", json=payload)
    return {"ok": True, "guild_id": guild_id, "event": _serialize_event(event)}


@mcp.tool(name="edit_guild_scheduled_event")
def edit_guild_scheduled_event(
    guildId: str | None = None,
    eventId: str = "",
    status: str | None = None,
    name: str | None = None,
    description: str | None = None,
    scheduledStartTime: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Edit a scheduled event."""
    guild_id = _resolve_guild_id(guildId)
    payload: dict[str, Any] = {}
    if status not in (None, ""):
        payload["status"] = _parse_int(status, field="status", minimum=1, maximum=4)
    if name not in (None, ""):
        payload["name"] = name
    if description is not None:
        payload["description"] = description
    if scheduledStartTime not in (None, ""):
        payload["scheduled_start_time"] = scheduledStartTime
    if location is not None:
        payload["entity_metadata"] = {"location": location} if location else None
    if not payload:
        raise DiscordApiError("No changes provided.")
    event = CLIENT.request("PATCH", f"/guilds/{guild_id}/scheduled-events/{eventId}", json=payload)
    return {"ok": True, "guild_id": guild_id, "event": _serialize_event(event)}


@mcp.tool(name="delete_guild_scheduled_event")
def delete_guild_scheduled_event(guildId: str | None = None, eventId: str = "") -> dict[str, Any]:
    """Delete a scheduled event."""
    guild_id = _resolve_guild_id(guildId)
    event = CLIENT.request("GET", f"/guilds/{guild_id}/scheduled-events/{eventId}")
    CLIENT.request("DELETE", f"/guilds/{guild_id}/scheduled-events/{eventId}")
    return {"ok": True, "guild_id": guild_id, "deleted_event": _serialize_event(event)}


@mcp.tool(name="list_guild_scheduled_events")
def list_guild_scheduled_events(
    guildId: str | None = None,
    withUserCount: str | None = None,
) -> dict[str, Any]:
    """List guild scheduled events."""
    guild_id = _resolve_guild_id(guildId)
    payload = CLIENT.request(
        "GET",
        f"/guilds/{guild_id}/scheduled-events",
        params={"with_user_count": str(_parse_bool(withUserCount, default=True)).lower()},
    )
    return {"ok": True, "guild_id": guild_id, "events": [_serialize_event(item) for item in payload]}


@mcp.tool(name="get_guild_scheduled_event_users")
def get_guild_scheduled_event_users(
    guildId: str | None = None,
    eventId: str = "",
    limit: str | None = None,
    withMember: str | None = None,
) -> dict[str, Any]:
    """List users interested in a scheduled event."""
    guild_id = _resolve_guild_id(guildId)
    payload = CLIENT.request(
        "GET",
        f"/guilds/{guild_id}/scheduled-events/{eventId}/users",
        params={
            "limit": _limit(limit, default=100, maximum=100),
            "with_member": str(_parse_bool(withMember, default=True)).lower(),
        },
    )
    return {"ok": True, "guild_id": guild_id, "event_id": eventId, "users": payload}


@mcp.tool(name="create_invite")
def create_invite(
    guildId: str | None = None,
    channelId: str = "",
    maxAge: str | None = None,
    maxUses: str | None = None,
    temporary: str | None = None,
    unique: str | None = None,
) -> dict[str, Any]:
    """Create an invite."""
    _resolve_guild_id(guildId)
    payload: dict[str, Any] = {}
    if maxAge not in (None, ""):
        payload["max_age"] = _parse_int(maxAge, field="maxAge", minimum=0)
    if maxUses not in (None, ""):
        payload["max_uses"] = _parse_int(maxUses, field="maxUses", minimum=0)
    if temporary not in (None, ""):
        payload["temporary"] = _parse_bool(temporary)
    if unique not in (None, ""):
        payload["unique"] = _parse_bool(unique)
    invite = CLIENT.request("POST", f"/channels/{channelId}/invites", json=payload)
    return {"ok": True, "invite": _serialize_invite(invite)}


@mcp.tool(name="list_invites")
def list_invites(guildId: str | None = None) -> dict[str, Any]:
    """List active invites in a guild."""
    guild_id = _resolve_guild_id(guildId)
    invites = CLIENT.request("GET", f"/guilds/{guild_id}/invites")
    return {"ok": True, "guild_id": guild_id, "invites": [_serialize_invite(item) for item in invites]}


@mcp.tool(name="delete_invite")
def delete_invite(inviteCode: str = "") -> dict[str, Any]:
    """Delete an invite by code or URL."""
    code = _normalize_invite_code(inviteCode)
    invite = CLIENT.request("GET", f"/invites/{code}")
    CLIENT.request("DELETE", f"/invites/{code}")
    return {"ok": True, "deleted_invite": _serialize_invite(invite)}


@mcp.tool(name="get_invite_details")
def get_invite_details(inviteCode: str = "", withCounts: str | None = None) -> dict[str, Any]:
    """Get invite details."""
    code = _normalize_invite_code(inviteCode)
    invite = CLIENT.request(
        "GET",
        f"/invites/{code}",
        params={"with_counts": str(_parse_bool(withCounts, default=True)).lower()},
    )
    return {"ok": True, "invite": _serialize_invite(invite)}


@mcp.tool(name="list_emojis")
def list_emojis(guildId: str | None = None) -> dict[str, Any]:
    """List guild emojis."""
    guild_id = _resolve_guild_id(guildId)
    emojis = CLIENT.request("GET", f"/guilds/{guild_id}/emojis")
    return {"ok": True, "guild_id": guild_id, "emojis": [_serialize_emoji(item) for item in emojis]}


@mcp.tool(name="get_emoji_details")
def get_emoji_details(guildId: str | None = None, emojiId: str = "") -> dict[str, Any]:
    """Get details for a guild emoji."""
    guild_id = _resolve_guild_id(guildId)
    emoji = CLIENT.request("GET", f"/guilds/{guild_id}/emojis/{emojiId}")
    return {"ok": True, "guild_id": guild_id, "emoji": _serialize_emoji(emoji)}


@mcp.tool(name="create_emoji")
def create_emoji(
    guildId: str | None = None,
    name: str = "",
    image: str | None = None,
    imageUrl: str | None = None,
    roles: str | None = None,
) -> dict[str, Any]:
    """Create a guild emoji."""
    guild_id = _resolve_guild_id(guildId)
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    if not image and not imageUrl:
        raise DiscordApiError("Either image or imageUrl is required.")
    image_payload = image or ""
    if imageUrl:
        image_payload = CLIENT.fetch_data_uri(imageUrl)
    elif image_payload and not image_payload.startswith("data:"):
        image_payload = f"data:image/png;base64,{image_payload}"
    payload: dict[str, Any] = {"name": name, "image": image_payload}
    role_ids = _split_csv(roles)
    if roles is not None:
        payload["roles"] = role_ids
    emoji = CLIENT.request("POST", f"/guilds/{guild_id}/emojis", json=payload)
    return {"ok": True, "guild_id": guild_id, "emoji": _serialize_emoji(emoji)}


@mcp.tool(name="edit_emoji")
def edit_emoji(
    guildId: str | None = None,
    emojiId: str = "",
    name: str | None = None,
    roles: str | None = None,
) -> dict[str, Any]:
    """Edit a guild emoji."""
    guild_id = _resolve_guild_id(guildId)
    payload: dict[str, Any] = {}
    if name not in (None, ""):
        payload["name"] = name
    if roles is not None:
        payload["roles"] = _split_csv(roles)
    if not payload:
        raise DiscordApiError("No changes provided.")
    emoji = CLIENT.request("PATCH", f"/guilds/{guild_id}/emojis/{emojiId}", json=payload)
    return {"ok": True, "guild_id": guild_id, "emoji": _serialize_emoji(emoji)}


@mcp.tool(name="delete_emoji")
def delete_emoji(guildId: str | None = None, emojiId: str = "") -> dict[str, Any]:
    """Delete a guild emoji."""
    guild_id = _resolve_guild_id(guildId)
    emoji = CLIENT.request("GET", f"/guilds/{guild_id}/emojis/{emojiId}")
    CLIENT.request("DELETE", f"/guilds/{guild_id}/emojis/{emojiId}")
    return {"ok": True, "guild_id": guild_id, "deleted_emoji": _serialize_emoji(emoji)}


@mcp.tool(name="create_webhook")
def create_webhook(channelId: str = "", name: str = "") -> dict[str, Any]:
    """Create a webhook on a channel."""
    if not name.strip():
        raise DiscordApiError("name cannot be empty")
    webhook = CLIENT.request("POST", f"/channels/{channelId}/webhooks", json={"name": name})
    return {"ok": True, "webhook": _serialize_webhook(webhook)}


@mcp.tool(name="delete_webhook")
def delete_webhook(webhookId: str = "") -> dict[str, Any]:
    """Delete a webhook."""
    CLIENT.request("DELETE", f"/webhooks/{webhookId}")
    return {"ok": True, "webhook_id": webhookId}


@mcp.tool(name="list_webhooks")
def list_webhooks(channelId: str = "") -> dict[str, Any]:
    """List webhooks on a channel."""
    webhooks = CLIENT.request("GET", f"/channels/{channelId}/webhooks")
    return {"ok": True, "channel_id": channelId, "webhooks": [_serialize_webhook(item) for item in webhooks]}


@mcp.tool(name="send_webhook_message")
def send_webhook_message(webhookUrl: str = "", message: str = "") -> dict[str, Any]:
    """Send a message through a webhook URL."""
    if not webhookUrl.strip():
        raise DiscordApiError("webhookUrl cannot be empty")
    if not message:
        raise DiscordApiError("message cannot be empty")
    separator = "&" if "?" in webhookUrl else "?"
    sent = CLIENT.request(
        "POST",
        "",
        absolute_url=f"{webhookUrl}{separator}wait=true",
        use_bot_auth=False,
        json={"content": message},
    )
    channel = {"id": sent.get("channel_id"), "guild_id": sent.get("guild_id")}
    return {"ok": True, "message": _serialize_message(sent, channel)}


def _run() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    _run()
