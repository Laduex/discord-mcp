"""Offline regression tests; import stubs stand in only for missing dependencies."""
import importlib.util
import json
import os
import sys
import types
import unittest
from copy import deepcopy
from unittest.mock import patch

if importlib.util.find_spec('mcp') is None:
    class FastMCP:
        def __init__(self, **kwargs):
            pass
        def tool(self, **kwargs):
            return lambda fn: fn
    for name in ('mcp', 'mcp.server', 'mcp.server.fastmcp'):
        sys.modules[name] = types.ModuleType(name)
    sys.modules['mcp.server.fastmcp'].FastMCP = FastMCP
if importlib.util.find_spec('requests') is None:
    requests = types.ModuleType('requests')
    requests.Session = lambda: None
    sys.modules['requests'] = requests
with patch.dict(os.environ, {'DISCORD_TOKEN': 'offline-token-never-real', 'DISCORD_GUILD_ID': '100'}):
    from src import server as s


def bits(*names):
    return sum(s.PERMISSION_BITS[n] for n in names)


def overwrite(who, kind, deny=0, allow=0):
    return dict(id=who, type=kind, deny=str(deny), allow=str(allow))


class MemberAccessTests(unittest.TestCase):
    def setUp(self):
        self.guild = dict(id='100', owner_id='999')
        self.member = dict(user=dict(id='200', username='member', token='webhook-secret'),
                           roles=['300', '400'], communication_disabled_until=None, token='webhook-secret')
        self.roles = [dict(id='100', name='@everyone', permissions=str(bits('VIEW_CHANNEL', 'SEND_MESSAGES', 'READ_MESSAGE_HISTORY', 'CONNECT'))),
                      dict(id='300', name='a', permissions='0'), dict(id='400', name='b', permissions='0')]
        self.channels = [dict(id='500', type=0, name='text', permission_overwrites=[])]
        self.threads = []
        self.calls = []
        self.errors = set()
        self.memberships = {}
        def request(method, path, **kwargs):
            self.calls.append((method, path))
            self.assertEqual(method, 'GET')
            if path in self.errors:
                raise s.DiscordApiError('offline-token-never-real webhook-secret')
            routes = {'/guilds/100': self.guild, '/guilds/100/members/200': self.member,
                      '/guilds/100/roles': self.roles, '/guilds/100/channels': self.channels,
                      '/guilds/100/threads/active': {'threads': self.threads}}
            routes.update(self.memberships)
            if path not in routes:
                raise AssertionError('Unexpected request: ' + path)
            return deepcopy(routes[path])
        self.client = patch.object(s.CLIENT, 'request', side_effect=request)
        self.client.start()
        self.addCleanup(self.client.stop)

    def run_tool(self, **kwargs):
        return s.get_member_access(userId='200', **kwargs)

    def perms(self, result):
        return set(result['channels'][0]['permissions'])

    def test_overwrite_precedence(self):
        flag = bits('SEND_MESSAGES')
        self.channels[0]['permission_overwrites'] = [overwrite('100', 0, flag), overwrite('300', 0, flag),
            overwrite('400', 0, allow=flag), overwrite('200', 1, flag)]
        self.assertNotIn('SEND_MESSAGES', self.perms(self.run_tool()))
        self.channels[0]['permission_overwrites'].pop()
        self.assertIn('SEND_MESSAGES', self.perms(self.run_tool()))
        self.channels[0]['permission_overwrites'].append(overwrite('200', 1, flag, flag))
        self.assertIn('SEND_MESSAGES', self.perms(self.run_tool()))

    def test_owner_admin_and_timeout_exemptions(self):
        self.member['communication_disabled_until'] = '2999-01-01T00:00:00Z'
        self.channels[0]['permission_overwrites'] = [overwrite('100', 0, bits('VIEW_CHANNEL'))]
        for owner in (True, False):
            with self.subTest(owner=owner):
                self.guild['owner_id'] = '200' if owner else '999'
                self.roles[1]['permissions'] = '0' if owner else str(bits('ADMINISTRATOR'))
                result = self.run_tool()
                self.assertEqual(set(result['guild_permissions']['permissions']), set(s.PERMISSION_BITS))
                self.assertEqual(self.perms(result), set(s.PERMISSION_BITS))
                self.assertFalse(result['timeout_applied'])

    def test_timeout_and_expiry(self):
        self.roles[1]['permissions'] = str(sum(s.PERMISSION_BITS.values()) & ~bits('ADMINISTRATOR'))
        self.member['communication_disabled_until'] = '2999-01-01T00:00:00Z'
        result = self.run_tool()
        self.assertTrue(result['timeout_applied'])
        self.assertEqual(self.perms(result), {'VIEW_CHANNEL', 'READ_MESSAGE_HISTORY'})
        self.assertEqual(set(result['guild_permissions']['permissions']), {'VIEW_CHANNEL', 'READ_MESSAGE_HISTORY'})
        self.member['communication_disabled_until'] = '2000-01-01T00:00:00Z'
        self.assertFalse(self.run_tool()['timeout_applied'])

    def test_implicit_denials(self):
        self.roles[1]['permissions'] = str(bits('EMBED_LINKS', 'ATTACH_FILES', 'SEND_POLLS', 'SPEAK', 'STREAM', 'USE_SOUNDBOARD', 'MANAGE_CHANNELS', 'MANAGE_ROLES'))
        for denied, removed in [('SEND_MESSAGES', {'EMBED_LINKS', 'ATTACH_FILES', 'SEND_POLLS'}),
                                 ('CONNECT', {'SPEAK', 'STREAM', 'USE_SOUNDBOARD', 'MANAGE_CHANNELS', 'MANAGE_ROLES'}),
                                 ('VIEW_CHANNEL', {'SEND_MESSAGES', 'CONNECT', 'READ_MESSAGE_HISTORY'})]:
            with self.subTest(denied=denied):
                self.channels[0]['type'] = 2 if denied == 'CONNECT' else 0
                self.channels[0]['permission_overwrites'] = [overwrite('100', 0, bits(denied))]
                self.assertTrue(removed.isdisjoint(self.perms(self.run_tool())))

    def test_base_role_union_and_member_allow(self):
        self.roles[1]['permissions'] = str(bits('EMBED_LINKS'))
        self.roles[2]['permissions'] = str(bits('ATTACH_FILES'))
        self.channels[0]['permission_overwrites'] = [
            overwrite('100', 0, bits('SEND_MESSAGES')),
            overwrite('300', 0, bits('SEND_MESSAGES')),
            overwrite('200', 1, allow=bits('SEND_MESSAGES'))]
        result = self.run_tool()
        self.assertTrue({'VIEW_CHANNEL', 'EMBED_LINKS', 'ATTACH_FILES'}.issubset(
            result['guild_permissions']['permissions']))
        self.assertTrue({'SEND_MESSAGES', 'EMBED_LINKS', 'ATTACH_FILES'}.issubset(self.perms(result)))
        self.assertEqual([role['id'] for role in result['roles']], ['300', '400'])

    def test_private_manager_and_archived_thread(self):
        self.roles[1]['permissions'] = str(bits('MANAGE_THREADS', 'SEND_MESSAGES_IN_THREADS'))
        self.threads = [dict(id='600', type=12, parent_id='500')]
        thread = self.run_tool()['channels'][1]
        self.assertTrue(thread['can_view_channel'])
        self.assertTrue(thread['can_send_messages'])
        self.threads[0]['thread_metadata'] = {'archived': True, 'locked': True}
        self.assertFalse(self.run_tool()['channels'][1]['can_send_messages'])

    def test_private_membership_success_uses_inherited_permissions(self):
        self.roles[1]['permissions'] = str(bits('SEND_MESSAGES_IN_THREADS'))
        self.threads = [dict(id='600', type=12, parent_id='500')]
        path = '/channels/600/thread-members/200'
        self.memberships[path] = dict(id='600', user_id='200', token='webhook-secret')
        row = self.run_tool()['channels'][1]
        self.assertTrue(row['can_view_channel'])
        self.assertTrue(row['can_send_messages'])
        self.assertEqual(self.calls.count(('GET', path)), 1)
        self.roles[1]['permissions'] = '0'
        row = self.run_tool()['channels'][1]
        self.assertTrue(row['can_view_channel'])
        self.assertFalse(row['can_send_messages'])
        self.assertNotIn('webhook-secret', json.dumps(row))

    def test_private_lookup_errors_are_unknown_and_redacted(self):
        self.roles[1]['permissions'] = str(bits('SEND_MESSAGES_IN_THREADS'))
        self.threads = [dict(id='600', type=12, parent_id='500')]
        self.errors.add('/channels/600/thread-members/200')
        result = self.run_tool()
        row = result['channels'][1]
        self.assertIsNone(row['can_view_channel'])
        self.assertIsNone(row['can_send_messages'])
        self.assertIn(('GET', '/channels/600/thread-members/200'), self.calls)
        self.assertNotIn('webhook-secret', json.dumps(result))
        self.assertNotIn('offline-token-never-real', json.dumps(result))
        self.assertTrue(row['limitations'])
        self.roles[1]['permissions'] = '0'
        self.assertFalse(self.run_tool()['channels'][1]['can_send_messages'])

    def test_private_probe_bound_and_skips(self):
        self.threads = [dict(id=str(600 + i), type=12, parent_id='500') for i in range(120)]
        result = self.run_tool(channelLimit=3)
        probes = [(m, p) for m, p in self.calls if '/thread-members/' in p]
        self.assertEqual(probes, [('GET', '/channels/600/thread-members/200'),
                                  ('GET', '/channels/601/thread-members/200')])
        self.assertLessEqual(len(probes), result['channel_limit'])
        for mode in ('denied', 'manager', 'disabled'):
            with self.subTest(mode=mode):
                self.calls.clear()
                self.channels[0]['permission_overwrites'] = (
                    [overwrite('100', 0, bits('VIEW_CHANNEL'))] if mode == 'denied' else [])
                self.roles[1]['permissions'] = str(bits('MANAGE_THREADS')) if mode == 'manager' else '0'
                self.run_tool(includeChannels=mode != 'disabled')
                self.assertFalse(any('/thread-members/' in p for _, p in self.calls))

    def test_current_bits(self):
        for name, bit in [('SET_VOICE_CHANNEL_STATUS', 48), ('PIN_MESSAGES', 51), ('BYPASS_SLOWMODE', 52)]:
            self.assertEqual(s.PERMISSION_BITS[name], 1 << bit)

    def test_thread_parent_and_thread_send(self):
        self.threads = [dict(id='600', type=11, parent_id='500', permission_overwrites=[overwrite('200', 1, bits('VIEW_CHANNEL'))])]
        self.channels[0]['permission_overwrites'] = [overwrite('100', 0, bits('SEND_MESSAGES'))]
        self.roles[1]['permissions'] = str(bits('SEND_MESSAGES_IN_THREADS', 'EMBED_LINKS'))
        thread = self.run_tool()['channels'][1]
        self.assertTrue(thread['can_send_messages'])
        self.assertIn('EMBED_LINKS', thread['permissions'])
        self.assertEqual(thread['permission_source_id'], '500')
        self.roles[1]['permissions'] = '0'
        self.assertFalse(self.run_tool()['channels'][1]['can_send_messages'])
        self.channels[0]['permission_overwrites'] = [overwrite('100', 0, bits('VIEW_CHANNEL'))]
        self.assertFalse(self.run_tool()['channels'][1]['can_view_channel'])

    def test_private_missing_parent_and_inaccessible_limitations(self):
        self.roles[1]['permissions'] = str(bits('SEND_MESSAGES_IN_THREADS'))
        self.threads = [dict(id='600', type=12, parent_id='500'), dict(id='601', type=11, parent_id='123')]
        result = self.run_tool()
        self.assertIsNone(result['channels'][1]['can_view_channel'])
        self.assertIsNone(result['channels'][1]['can_send_messages'])
        self.assertIsNone(result['channels'][2]['can_view_channel'])
        self.assertTrue(result['limitations'])
        self.errors.add('/guilds/100/threads/active')
        result = self.run_tool()
        self.assertTrue(result['limitations'])
        self.assertNotIn('webhook-secret', json.dumps(result))
        self.errors.add('/guilds/100/channels')
        self.assertEqual(self.run_tool()['channels'], [])

    def test_bounds_validation_get_only_and_no_secrets(self):
        self.member['nick'] = 'offline-token-never-real'
        self.channels[0]['name'] = 'https://discord.com/api/webhooks/123/webhook-secret'
        self.channels *= 120
        self.assertEqual(len(self.run_tool()['channels']), 25)
        self.assertEqual(len(self.run_tool(channelLimit=100)['channels']), 100)
        result = self.run_tool(channelLimit=2)
        self.assertEqual(len(result['channels']), 2)
        self.assertTrue(result['channels_truncated'])
        self.assertNotIn('webhook-secret', json.dumps(result))
        self.assertNotIn('offline-token-never-real', json.dumps(result))
        self.calls.clear()
        self.assertEqual(self.run_tool(includeChannels=False)['channels'], [])
        self.assertFalse(any('channels' in p or 'threads' in p for _, p in self.calls))
        for kwargs in ({'channelLimit': 0}, {'channelLimit': 101}, {'channelLimit': True},
                       {'channelLimit': 1.5}, {'includeChannels': 'bad'}, {'guildId': '../bad'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(s.DiscordApiError):
                self.run_tool(**kwargs)
        for user in ('', ' ', '../bad'):
            with self.assertRaises(s.DiscordApiError):
                s.get_member_access(userId=user)
        self.errors.add('/guilds/100/members/200')
        with self.assertRaises(s.DiscordApiError) as error:
            self.run_tool()
        self.assertNotIn('webhook-secret', str(error.exception))
        self.assertNotIn('offline-token-never-real', str(error.exception))


if __name__ == '__main__':
    unittest.main()
