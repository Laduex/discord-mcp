"""Read-only member access inspection. No raw REST objects or errors are returned."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Callable

from .discord_api import DiscordApiError

# Guild-scoped permissions survive an implicit VIEW_CHANNEL denial. All other
# known permissions describe channel actions, including MANAGE_ROLES in channels.
GUILD_PERMISSIONS = {
    'KICK_MEMBERS', 'BAN_MEMBERS', 'ADMINISTRATOR', 'MANAGE_GUILD',
    'VIEW_AUDIT_LOG', 'VIEW_GUILD_INSIGHTS', 'CHANGE_NICKNAME',
    'MANAGE_NICKNAMES', 'MANAGE_GUILD_EXPRESSIONS', 'MODERATE_MEMBERS',
    'VIEW_CREATOR_MONETIZATION_ANALYTICS', 'CREATE_GUILD_EXPRESSIONS',
    'MANAGE_EVENTS', 'CREATE_EVENTS',
}
TEXT_DEPENDENCIES = {
    'SEND_TTS_MESSAGES', 'MENTION_EVERYONE', 'EMBED_LINKS', 'ATTACH_FILES',
    'SEND_VOICE_MESSAGES', 'SEND_POLLS',
}
VOICE_DEPENDENCIES = {
    'PRIORITY_SPEAKER', 'STREAM', 'SPEAK', 'MUTE_MEMBERS', 'DEAFEN_MEMBERS',
    'MOVE_MEMBERS', 'USE_VAD', 'REQUEST_TO_SPEAK', 'USE_EMBEDDED_ACTIVITIES',
    'USE_SOUNDBOARD', 'USE_EXTERNAL_SOUNDS', 'SET_VOICE_CHANNEL_STATUS',
}
THREAD_TYPES = {10, 11, 12}


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,20}', value.strip()):
        raise DiscordApiError(f'{field} must be a numeric Discord ID (1-20 digits).')
    return value.strip()


def inspect_member(request: Callable[..., Any], permissions: dict[str, int], *,
                   guild_id: str, user_id: str, include_channels: bool,
                   channel_limit: int, token: str) -> dict[str, Any]:
    guild_id = _id(guild_id, 'guildId')
    user_id = _id(user_id, 'userId')

    def get(path: str) -> Any:
        try:
            return request('GET', path)
        except Exception:
            # Discord error bodies (and transport errors) may contain secrets.
            raise DiscordApiError('Member access REST lookup failed; data may be inaccessible to the bot.') from None

    def mask(names: set[str]) -> int:
        return sum(permissions[n] for n in names)

    def describe(value: int) -> dict[str, Any]:
        return {'permissions_raw': str(value),
                'permissions': [n for n, flag in permissions.items() if value & flag]}

    all_known = sum(permissions.values())
    guild = get(f'/guilds/{guild_id}')
    member = get(f'/guilds/{guild_id}/members/{user_id}')
    roles = get(f'/guilds/{guild_id}/roles')
    assigned_ids = set(member.get('roles', [])) - {guild_id}
    role_map = {r['id']: r for r in roles}
    if guild_id not in role_map or not assigned_ids.issubset(role_map):
        raise DiscordApiError('Required member roles are missing from the guild role response.')
    base = int(role_map[guild_id].get('permissions', '0'))
    for rid in assigned_ids:
        base |= int(role_map[rid].get('permissions', '0'))
    owner = guild.get('owner_id') == user_id
    admin = bool(base & permissions['ADMINISTRATOR'])
    bypass = owner or admin
    base = all_known if bypass else base
    until = member.get('communication_disabled_until')
    timeout_active = False
    if until:
        try:
            timeout_active = datetime.fromisoformat(until.replace('Z', '+00:00')).astimezone(UTC) > datetime.now(UTC)
        except (ValueError, TypeError):
            raise DiscordApiError('Invalid member timeout timestamp.') from None
    timeout_applied = timeout_active and not bypass
    timeout_mask = mask({'VIEW_CHANNEL', 'READ_MESSAGE_HISTORY'})
    limitations = [
        'Computed permissions are a REST snapshot, not a guarantee that an action will succeed. Role hierarchy, guild rules, verification, channel type and runtime restrictions still apply.',
        'Channel discovery is limited to channels and active threads returned to this bot. Inaccessible or archived threads are not enumerated; omission does not prove the member lacks access.',
        'Private thread membership is probed for returned threads when inherited access is possible and MANAGE_THREADS is absent. Lookup errors, including 404, leave membership unknown because absence and bot inaccessibility cannot be distinguished. Bot membership does not establish target membership.',
    ]
    output: dict[str, Any] = {
        'ok': True, 'guild_id': guild_id,
        'member': {'id': user_id, 'username': member.get('user', {}).get('username'),
                   'global_name': member.get('user', {}).get('global_name'), 'nick': member.get('nick')},
        'is_owner': owner, 'is_administrator': admin,
        'communication_disabled_until': until, 'timeout_active': timeout_active,
        'timeout_applied': timeout_applied,
        'roles': [{'id': rid, 'name': role_map[rid].get('name'),
                   **describe(int(role_map[rid].get('permissions', '0')))}
                  for rid in sorted(assigned_ids)[:250]],
        'roles_truncated': len(assigned_ids) > 250,
        'everyone_role': {'id': guild_id, **describe(int(role_map[guild_id].get('permissions', '0')))},
        'guild_permissions': describe(base & timeout_mask if timeout_applied else base),
        'channels': [], 'channels_included': include_channels,
        'channel_limit': channel_limit, 'channels_truncated': False,
        'limitations': limitations,
    }

    def effective(channel: dict[str, Any], thread: bool) -> int:
        if bypass:
            return all_known
        value = base
        overwrites = channel.get('permission_overwrites', [])
        # Everyone first, then aggregate roles (allows win), then member.
        groups = [
            [o for o in overwrites if str(o.get('type')) == '0' and o['id'] == guild_id],
            [o for o in overwrites if str(o.get('type')) == '0' and o['id'] in assigned_ids],
            [o for o in overwrites if str(o.get('type')) == '1' and o['id'] == user_id],
        ]
        for group in groups:
            deny = allow = 0
            for overwrite in group:
                deny |= int(overwrite.get('deny', '0'))
                allow |= int(overwrite.get('allow', '0'))
            value = (value & ~deny) | allow
        if timeout_applied:
            value &= timeout_mask
        if not value & permissions['VIEW_CHANNEL']:
            value &= mask(GUILD_PERMISSIONS)
        send_flag = 'SEND_MESSAGES_IN_THREADS' if thread else 'SEND_MESSAGES'
        if not value & permissions[send_flag]:
            value &= ~mask(TEXT_DEPENDENCIES)
        if not value & permissions['CONNECT']:
            value &= ~mask(VOICE_DEPENDENCIES)
            if channel.get('type') in {2, 13}:
                value &= ~mask({'MANAGE_CHANNELS', 'MANAGE_ROLES'})
        return value

    if include_channels:
        channels: list[dict[str, Any]] = []
        threads: list[dict[str, Any]] = []
        for route, target, key in [('channels', channels, None), ('threads/active', threads, 'threads')]:
            try:
                response = get(f'/guilds/{guild_id}/{route}')
                target.extend(response[key] if key else response)
            except DiscordApiError:
                limitations.append(f'Bot could not retrieve {route}; channel coverage is incomplete.')
        # Guild channels precede active threads. Parent lookup uses the entire
        # snapshot even when the parent falls outside the output limit.
        by_id = {c['id']: c for c in channels}
        candidates = channels + threads
        output['channels_truncated'] = len(candidates) > channel_limit
        for channel in candidates[:channel_limit]:
            thread = channel.get('type') in THREAD_TYPES
            source = by_id.get(channel.get('parent_id')) if thread else channel
            row: dict[str, Any] = {
                'id': channel['id'], 'name': channel.get('name'), 'type': channel.get('type'),
                'parent_id': channel.get('parent_id'),
                'permission_source_id': source['id'] if source else None,
                'permissions_raw': None, 'permissions': None,
                'can_view_channel': None, 'can_send_messages': None,
                'limitations': [],
            }
            if source is None:
                row['limitations'].append('Parent channel permissions unavailable; thread access is unknown.')
            else:
                value = effective(source, thread)
                row.update(describe(value))
                view = bool(value & permissions['VIEW_CHANNEL'])
                send = view and bool(value & permissions['SEND_MESSAGES_IN_THREADS' if thread else 'SEND_MESSAGES'])
                row['can_view_channel'] = view
                # Text send applies only to message-bearing channels, not
                # categories or forum/media containers (which create posts).
                row['can_send_messages'] = send if channel.get('type') in {0, 2, 5, 10, 11, 12, 13} else False
                if channel.get('type') == 12 and view and not value & permissions['MANAGE_THREADS']:
                    try:
                        # Probe only returned rows, so there are at most channel_limit
                        # membership lookups. Never interpret a failed lookup as absence.
                        get(f"/channels/{channel['id']}/thread-members/{user_id}")
                    except DiscordApiError:
                        row['can_view_channel'] = None
                        row['can_send_messages'] = None if send else False
                        row['limitations'].append('Private thread membership lookup failed; membership remains unknown because absence and bot inaccessibility cannot be distinguished.')
                metadata = channel.get('thread_metadata', {})
                if thread and metadata.get('archived'):
                    row['can_send_messages'] = False
                    row['limitations'].append('Archived thread must be unarchived before sending; locked threads require MANAGE_THREADS to unarchive.')
            output['channels'].append(row)

    def safe(value: Any) -> Any:
        if isinstance(value, str):
            value = value.replace(token, '[REDACTED]') if token else value
            value = re.sub(r'(https?://[^\s/]+/api(?:/v\d+)?/webhooks/\d+/)[^\s/?]+', r'\1[REDACTED]', value)
            return value[:512]
        if isinstance(value, dict):
            return {k: safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [safe(v) for v in value]
        return value
    return safe(output)
