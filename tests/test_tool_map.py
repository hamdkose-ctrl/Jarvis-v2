"""Harita: gerçek politika deposu, sahiplik ve Bridge sözleşmesi."""
import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import llm, permission_audit, permission_gate, permission_grants, permission_policy, requests_state
from modules import tool_map


class ToolMapTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        root = Path(td.name)
        self.enterContext(patch.object(permission_policy, 'ROOT', root / 'policies'))
        self.enterContext(patch.object(permission_grants, 'ROOT', root / 'grants'))
        self.enterContext(patch.object(permission_audit, 'DATA_DIR', root))
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        token = requests_state._current.set(None); self.addCleanup(requests_state._current.reset, token)
        self.contract = {'id': 'demo', 'name': 'Örnek', 'area': 'cihaz', 'icon': 'gear',
                         'actions': [{'id': 'open', 'name': 'Aç', 'desc': 'Belge aç',
                                      'class': 'local_reversible', 'params': {}}],
                         'status': lambda: {'state': 'not_connected', 'detail': 'Bağlantı bekliyor'},
                         'cancel': Mock()}
        self.enterContext(patch('modules.tool_contract.load_all', return_value={'demo': self.contract}))

    def tools(self, owner='alice'):
        return {t['id']: t for t in tool_map.snapshot(owner)['tools']}

    def test_builtins_and_contracts_have_json_shape_and_locked_classes(self):
        result = tool_map.snapshot('alice')
        self.assertEqual(set(result), {'tools', 'placeholders'})
        json.dumps(result)
        tools = self.tools()
        self.assertEqual(set(tools), {'desktop', 'browser', 'outbox', 'demo'})
        for name in ('desktop', 'browser', 'outbox'):
            actions = tools[name]['actions']
            self.assertEqual({a['class'] for a in actions}, permission_gate.CLASSES)
            for action in actions:
                self.assertTrue({'id', 'name', 'desc', 'class', 'policy', 'until'} <= set(action))
                self.assertEqual(action['policy'], 'locked' if action['class'] in permission_policy.LOCKED else 'ask')
        self.assertEqual(tools['demo']['state'], 'not_connected')
        self.contract['cancel'].assert_not_called()

    def test_policy_changes_are_owner_scoped_and_class_scoped(self):
        self.assertEqual(tool_map.set_policy('alice', 'demo', 'open', 'deny'), {'ok': True})
        self.assertEqual(self.tools()['demo']['actions'][0]['policy'], 'deny')
        self.assertEqual(tool_map.set_policy('alice', 'outbox', 'message_out', 'allow'), {'ok': True})
        self.assertEqual(permission_grants.load('alice')['message_out'], {})
        token = llm._key_context.set('bob')
        try:
            self.assertEqual(self.tools('bob')['demo']['actions'][0]['policy'], 'ask')
            self.assertIsNone(tool_map.snapshot('alice'))
            self.assertIsNone(tool_map.set_policy('alice', 'demo', 'open', 'allow'))
        finally:
            llm._key_context.reset(token)
        self.assertEqual(permission_policy.get('alice', 'demo', 'local_reversible'), 'deny')

    def test_invalid_and_locked_changes_never_write(self):
        with patch.object(permission_policy, 'set') as write:
            for args in [('missing', 'read', 'allow'), ('desktop', 'missing', 'deny'),
                         ('desktop', 'read', 'BAD'), ('desktop', 'money_credential', 'allow'),
                         ('browser', 'system_config', 'deny'), ([], 'read', 'allow')]:
                self.assertIsNone(tool_map.set_policy('alice', *args))
            write.assert_not_called()

    def test_recent_decisions_are_scoped_and_exclude_message_fields(self):
        permission_audit.record('alice', 'deny', 'message_out', 'PRIVATE BODY', 'outbox', 'PRIVATE REASON')
        permission_grants.grant_message('alice', 'alice@example.org', 600)
        row = self.tools()['outbox']
        self.assertEqual(row['last'][0]['decision'], 'deny')
        self.assertNotIn('PRIVATE', json.dumps(row))
        expiry = next(a['until'] for a in row['actions'] if a['class'] == 'message_out')
        self.assertGreater(expiry, 0)
        self.assertTrue(all(not t['last'] for k, t in self.tools().items() if k != 'outbox'))

    def test_failures_return_none_and_record_diagnostics(self):
        for target, invoke in [('get', lambda: tool_map.snapshot('alice')),
                               ('set', lambda: tool_map.set_policy('alice', 'desktop', 'read', 'deny'))]:
            with patch.object(permission_policy, target, side_effect=RuntimeError('PRIVATE')), \
                    patch.object(tool_map, '_record_failure') as record:
                self.assertIsNone(invoke())
                record.assert_called_once()

    def test_contract_policy_names_cannot_alias_each_other(self):
        first = dict(self.contract, id='a-b')
        second = dict(self.contract, id='a_b')
        with patch('modules.tool_contract.load_all', return_value={'a-b': first, 'a_b': second}), \
                patch.object(tool_map, '_record_failure'), patch.object(permission_policy, 'set') as write:
            self.assertIsNone(tool_map.set_policy('alice', 'a-b', 'open', 'deny'))
            self.assertIsNone(tool_map.snapshot('alice'))
            write.assert_not_called()

    def test_bridge_routes_active_owner_and_fails_closed(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'web.py').read_bytes())
        bridge = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Bridge')
        methods = [n for n in bridge.body if isinstance(n, ast.FunctionDef) and n.name in ('map', 'map_set_policy')]
        record = Mock()
        scope = {'_p': lambda: SimpleNamespace(slug='alice'), '_record_failure': record}
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'bridge-map', 'exec'), scope)
        with patch.object(tool_map, 'snapshot', return_value={'tools': []}) as snapshot:
            self.assertEqual(scope['map'](None), {'tools': []})
            snapshot.assert_called_once_with('alice')
        with patch.object(tool_map, 'set_policy', return_value={'ok': True}) as setter:
            self.assertEqual(scope['map_set_policy'](None, 'desktop', 'read', 'deny'), {'ok': True})
            setter.assert_called_once_with('alice', 'desktop', 'read', 'deny')
        with patch.object(tool_map, 'snapshot', side_effect=RuntimeError('PRIVATE')):
            self.assertIsNone(scope['map'](None))
            record.assert_called_once()


if __name__ == '__main__':
    unittest.main()
