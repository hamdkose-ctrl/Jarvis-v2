"""Direct adapter-metadata tests; readiness is not permission or live evidence."""
import copy
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

# A focused run can import config before any other tests: keep that startup
# (including config's mkdir/read operations) away from the real user directory.
_import_data = tempfile.TemporaryDirectory(prefix='specialist-contract-tests-')
with patch.dict(os.environ, {'JARVIS_DATA_DIR': _import_data.name}):
    from modules import (specialist_contracts as contracts, service_store, llm,
                         requests_state, team_center, developer, goal_tools, task_tools)


class SpecialistContractsTests(unittest.TestCase):
    def setUp(self):
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        request = requests_state._current.set(None)
        self.addCleanup(requests_state._current.reset, request)
        self.members = self.enterContext(patch.object(team_center, 'members', return_value=[]))
        self.status = self.enterContext(patch.object(developer, 'status', return_value={}))
        self.blocked = self.enterContext(patch.object(contracts.privacy, 'blocked', return_value=False))
        self.which = self.enterContext(patch.object(contracts.shutil, 'which', return_value=None))
        self.identity = self.enterContext(patch.object(service_store, 'identity', wraps=service_store.identity))
        self.ask = self.enterContext(patch.object(llm, 'ask', side_effect=AssertionError('No model call')))

    def describe_tools(self, tools, owner='alice'):
        self.members.return_value = [{'id': 'expert', 'name': 'Uzman', 'tools': list(tools)}]
        result = contracts.describe(owner)
        self.assertEqual(len(result['specialists']), 1)
        specialist = result['specialists'][0]
        self.assertEqual((specialist['id'], specialist['name']), ('expert', 'Uzman'))
        self.assertIs(specialist['permissions_granted'], False)
        self.ask.assert_not_called()
        return {row['tool']: row for row in specialist['tools']}, result

    def test_describe_empty_registry_has_explicit_limits_without_claiming_operation_success(self):
        result = contracts.describe('alice')
        self.assertEqual(result['specialists'], [])
        self.assertEqual(len(result['limits']), 3)
        limits = ' '.join(result['limits'])
        self.assertIn('yeni anahtar, hesap veya işlem yetkisi sağlamaz', limits)
        self.assertIn('dış MCP kod çalıştırma', limits)
        self.assertIn('yalnız gerçek operasyon sonucu', limits)
        self.identity.assert_called_once_with('alice')
        self.status.assert_called_once_with('alice')
        self.members.assert_called_once_with('alice')
        self.which.assert_not_called()
        self.blocked.assert_not_called()
        self.ask.assert_not_called()

    def test_describe_every_declared_contract_returns_concrete_delivery_and_scope(self):
        expected_tools = {'research', 'writer', 'media', 'coder', 'account', 'publish',
                          'browser', 'document', 'data', 'monitor', 'capability', 'verify'}
        self.assertEqual(set(contracts.CONTRACTS), expected_tools)
        rows, _ = self.describe_tools(sorted(expected_tools))
        for tool in expected_tools:
            with self.subTest(tool=tool):
                self.assertEqual(set(rows[tool]), {'tool', 'registered', 'deliverable', 'scope', 'readiness'})
                self.assertEqual((rows[tool]['deliverable'], rows[tool]['scope']), contracts.CONTRACTS[tool])
                self.assertTrue(rows[tool]['deliverable'].strip())
                self.assertTrue(rows[tool]['scope'].strip())
        # Technical evidence must not be presented as semantic/content accuracy.
        self.assertIn('olgu doğruluğu dosya varlığından çıkarılmaz', rows['writer']['scope'])
        self.assertIn('anlamsal olarak doğru olduğu anlamına gelmez', rows['verify']['scope'])
        self.assertIn('Uzman atanması dış gönderim izni vermez', rows['publish']['scope'])
        self.assertIn('kaynağa otomatik uygulama yok', rows['coder']['scope'])

    def test_describe_registration_uses_either_real_adapter_catalog_not_contract_membership(self):
        with patch.dict(goal_tools.LOCAL, {'local_only': 'local'}, clear=True), \
                patch.dict(task_tools.CATALOG, {'catalog_only': {}}, clear=True):
            rows, _ = self.describe_tools(['local_only', 'catalog_only', 'research', 'unknown'])
        self.assertIs(rows['local_only']['registered'], True)
        self.assertIs(rows['catalog_only']['registered'], True)
        self.assertIs(rows['research']['registered'], False)
        self.assertIs(rows['unknown']['registered'], False)
        self.assertEqual(rows['unknown']['deliverable'], 'Adaptörün durumlu yerel sonucu')
        self.assertEqual(rows['unknown']['scope'], 'Mevcut adaptör izinleri çalışma sırasında denetlenir.')
        self.assertEqual(rows['unknown']['readiness'], 'runtime_check_required')

    def test_describe_coder_requires_both_enabled_and_unlocked_and_grants_no_permission(self):
        for state, expected in [({}, 'locked'), ({'enabled': True}, 'locked'),
                                ({'unlocked': True}, 'locked'),
                                ({'enabled': False, 'unlocked': True}, 'locked'),
                                ({'enabled': True, 'unlocked': False}, 'locked'),
                                ({'enabled': True, 'unlocked': True}, 'unlocked')]:
            with self.subTest(state=state):
                self.status.return_value = state
                rows, _ = self.describe_tools(['coder', 'publish'])
                self.assertEqual(rows['coder']['readiness'], expected)
                self.assertEqual(rows['publish']['readiness'], 'runtime_check_required')

    def test_describe_media_needs_both_binaries_not_only_ffmpeg(self):
        for ffmpeg, ffprobe, expected in [('/ffmpeg', '/ffprobe', 'local_prerequisites_present'),
                                        ('/ffmpeg', None, 'missing_ffmpeg_or_ffprobe'),
                                        (None, '/ffprobe', 'missing_ffmpeg_or_ffprobe'),
                                        (None, None, 'missing_ffmpeg_or_ffprobe')]:
            with self.subTest(ffmpeg=ffmpeg, ffprobe=ffprobe):
                self.which.side_effect = lambda name: {'ffmpeg': ffmpeg, 'ffprobe': ffprobe}[name]
                rows, _ = self.describe_tools(['media'])
                self.assertEqual(rows['media']['readiness'], expected)
                self.assertIn('Görsel içerik ve kaynak lisansı ayrıca kontrol edilir', rows['media']['scope'])

    def test_describe_web_privacy_blocks_research_and_browser_only(self):
        for blocked in (False, True):
            with self.subTest(blocked=blocked):
                self.blocked.return_value = blocked
                self.blocked.reset_mock()
                rows, _ = self.describe_tools(['research', 'browser', 'writer', 'account', 'document', 'verify'])
                for tool in ('research', 'browser'):
                    self.assertEqual(rows[tool]['readiness'], 'privacy_blocked' if blocked else 'runtime_check_required')
                self.assertEqual(rows['writer']['readiness'], 'local_adapter_available')
                for tool in ('account', 'document', 'verify'):
                    self.assertEqual(rows[tool]['readiness'], 'runtime_check_required')
                self.assertEqual(self.blocked.call_args_list, [unittest.mock.call('web')] * 2)

    def test_describe_data_monitor_capability_do_not_claim_live_connections(self):
        rows, _ = self.describe_tools(['data', 'monitor', 'capability'])
        for row in rows.values():
            self.assertEqual(row['readiness'], 'adapter_available_connections_checked_per_operation')
        self.assertIn('model çağrısı olmadan', rows['monitor']['scope'])
        self.assertIn('çalışan entegrasyon kanıtı değildir', rows['capability']['scope'])
        self.which.assert_not_called()
        self.blocked.assert_not_called()

    def test_describe_empty_tools_and_long_display_metadata_are_not_commands(self):
        long_name = '<script>' + 'ğ' * 10000
        source = [{'id': 'first', 'name': long_name, 'tools': []},
                  {'id': 'second', 'name': '', 'tools': ['writer']}]
        self.members.return_value = source
        before = copy.deepcopy(source)
        result = contracts.describe('alice')
        self.assertEqual([row['id'] for row in result['specialists']], ['first', 'second'])
        self.assertEqual(result['specialists'][0]['name'], long_name)
        self.assertEqual(result['specialists'][0]['tools'], [])
        result['specialists'][1]['tools'].clear()
        result['limits'].clear()
        self.assertEqual(source, before)
        self.assertEqual(len(contracts.describe('alice')['limits']), 3)
        self.ask.assert_not_called()

    def test_describe_invalid_owner_type_empty_path_and_overlong_rejected_before_adapters(self):
        for owner in (None, True, 1, [], {}, '', '../alice', 'alice/bob', 'x' * 101):
            with self.subTest(owner=owner), self.assertRaises(PermissionError):
                contracts.describe(owner)
        self.members.assert_not_called()
        self.status.assert_not_called()
        self.which.assert_not_called()
        self.blocked.assert_not_called()

    def test_describe_accepts_owner_length_boundaries_in_matching_context(self):
        for owner in ('a', 'a' * 100):
            with self.subTest(length=len(owner)):
                token = llm._key_context.set(owner)
                try:
                    self.assertEqual(contracts.describe(owner)['specialists'], [])
                    self.members.assert_called_with(owner)
                    self.status.assert_called_with(owner)
                finally:
                    llm._key_context.reset(token)

    def test_describe_foreign_context_or_request_cannot_read_specialists(self):
        for owner, request in [('bob', None), ('alice', ('bob', 'request-id'))]:
            with self.subTest(owner=owner):
                token = requests_state._current.set(request)
                try:
                    with self.assertRaises(PermissionError):
                        contracts.describe(owner)
                finally:
                    requests_state._current.reset(token)
        self.members.assert_not_called()
        self.status.assert_not_called()

    def test_describe_adapter_errors_propagate_instead_of_inventing_readiness(self):
        for adapter in (self.status, self.members):
            with self.subTest(adapter=adapter):
                adapter.side_effect = RuntimeError('adapter unavailable')
                try:
                    with self.assertRaisesRegex(RuntimeError, 'adapter unavailable'):
                        contracts.describe('alice')
                finally:
                    adapter.side_effect = None


if __name__ == '__main__':
    unittest.main()
