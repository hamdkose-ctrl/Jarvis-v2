"""Linux-safe fixtures: no live accounts, registry, audio streams or HTTP calls."""
import ctypes
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('pc_duman_under_test', Path(__file__).resolve().parents[1] / 'scripts/pc_duman_testi.py')
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
_previous_bytecode_setting = sys.dont_write_bytecode
try:
    SPEC.loader.exec_module(smoke)
finally:
    sys.dont_write_bytecode = _previous_bytecode_setting
SECRET = 'PRIVATE_TOKEN_MAIL_PATH_NEVER_PRINT_123'


class Registry(types.ModuleType):
    HKEY_CLASSES_ROOT, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE = 'CR', 'CU', 'LM'
    KEY_READ, KEY_WOW64_64KEY, KEY_WOW64_32KEY = 1, 256, 512

    def __init__(self):
        super().__init__('winreg')
        self.values = {}
        self.OpenKey = Mock(side_effect=self.open_key)
        self.QueryValueEx = Mock(side_effect=lambda key, name: (self.values[key + (name,)], 1))

    def open_key(self, hive, path, reserved, access):
        if not any(key[:2] == (hive, path) for key in self.values):
            raise FileNotFoundError(SECRET)
        key = Mock()
        key.__enter__ = Mock(return_value=(hive, path))
        key.__exit__ = Mock(return_value=False)
        return key

    def allow_microphone(self):
        root = r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
        for hive in (self.HKEY_CURRENT_USER, self.HKEY_LOCAL_MACHINE):
            for path in (root, root + r'\NonPackaged'):
                self.values[hive, path, 'Value'] = 'Allow'


class SmokeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo, self.data, self.reports = [self.root / name for name in ('repo', 'private', 'reports')]
        for path in (self.repo / 'modules', self.data / 'users', self.reports):
            path.mkdir(parents=True)
        self.ctx = smoke.Context(self.repo, self.data, self.reports, 'hamdi', windows=True,
                                 now=datetime(2026, 10, 18, 12, tzinfo=smoke.TR), encoding='utf-8')
        self.write(self.repo / 'config.py', "DEFAULT_USER = 'Hamdi'\nraise AssertionError('must not import config')\n")
        self.write(self.repo / 'requirements.txt', '-r requirements.lock.txt\n')
        self.write(self.repo / 'requirements.lock.txt', 'dep==1.0\n')
        self.write(self.data / 'users/hamdi.json', json.dumps({'name': SECRET}))
        for name in ('google_api.py', 'usage_meter.py', 'engine_runtime.py'):
            self.write(self.repo / 'modules' / name, "raise AssertionError('must not import Jarvis')\n")
        real = Path(__file__).resolve().parents[1] / 'modules/files.py'
        self.write(self.repo / 'modules/files.py', real.read_text(encoding='utf-8'))
        self.registry = Registry()
        self.registry.allow_microphone()
        self.registry_patch = patch.dict(sys.modules, {'winreg': self.registry})
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def checked(self, function):
        with patch.object(smoke, 'CHECKS', (('deneme', function),)):
            row = smoke.run_checks(self.ctx)[0]
        self.assertNotIn(SECRET, row[2])
        return row[1:]

    def token(self, **changes):
        saved = {'token': SECRET, 'refresh_token': SECRET,
                 'client_secret': SECRET, 'expiry': '2026-10-19T00:00:00Z',
                 'scopes': ['https://www.googleapis.com/auth/gmail.readonly']}
        saved.update(changes)
        path = self.data / 'google_users/hamdi/google_token.json'
        self.write(path, json.dumps(saved))
        return path

    def quota(self, path=None, **changes):
        row = {'t': '2026-10-18T10:00:00+03:00', 'p': SECRET, 'm': SECRET,
               's': SECRET, 'r': 'ok', 'i': 10, 'o': 3}
        row.update(changes)
        self.write(path or self.data / 'kota/hamdi.jsonl', json.dumps(row) + '\n')

    def test_01_python_packages_pass(self):
        with patch.object(smoke.sys, 'version_info', (3, 13)), patch.object(smoke.metadata, 'version', return_value='1.0'):
            self.assertEqual(self.checked(smoke.check_python)[0], smoke.PASS)

    def test_01_python_packages_fail_missing_distribution(self):
        with patch.object(smoke.metadata, 'version', side_effect=smoke.metadata.PackageNotFoundError('dep')):
            self.assertEqual(self.checked(smoke.check_python)[0], smoke.FAIL)

    def test_01_recursive_requirements_and_version_warning(self):
        self.write(self.repo / 'requirements.lock.txt', '-r requirements.txt\ndep==1.0\n')
        self.assertEqual(smoke.requirements(self.repo / 'requirements.txt', self.repo), ['dep==1.0'])
        with patch.object(smoke.metadata, 'version', return_value='2.0'):
            self.assertEqual(self.checked(smoke.check_python)[0], smoke.WARN)

    def test_01_outside_requirements_and_missing_file_fail_safely(self):
        self.write(self.repo / 'requirements.txt', '-r ../private/settings.json')
        self.assertEqual(self.checked(smoke.check_python)[0], smoke.FAIL)
        (self.repo / 'requirements.txt').unlink()
        self.assertEqual(self.checked(smoke.check_python)[0], smoke.FAIL)

    def test_01_old_python_and_unparsed_requirements(self):
        with patch.object(smoke.sys, 'version_info', (3, 8)):
            self.assertEqual(self.checked(smoke.check_python)[0], smoke.FAIL)
        self.write(self.repo / 'requirements.lock.txt', 'dep>=1.0; python_version >= "3.10"')
        self.assertEqual(self.checked(smoke.check_python)[0], smoke.WARN)

    def test_02_encoding_pass_and_temporary_file_cleaned(self):
        self.assertEqual(self.checked(smoke.check_encoding)[0], smoke.PASS)
        self.assertEqual(list(self.reports.iterdir()), [])

    def test_02_encoding_fail_isolated_without_exception_contents(self):
        with patch.object(smoke.tempfile, 'NamedTemporaryFile', side_effect=PermissionError(SECRET)):
            self.assertEqual(self.checked(smoke.check_encoding)[0], smoke.FAIL)

    def test_02_console_ascii_warns_instead_of_dropping_turkish(self):
        self.ctx.encoding = 'ascii'
        self.assertEqual(self.checked(smoke.check_encoding)[0], smoke.WARN)
        class Ascii(io.StringIO):
            encoding = 'ascii'
            def write(self, value):
                value.encode('ascii')
                return super().write(value)
        stream = Ascii()
        smoke.console_write(smoke.SAMPLE, stream)
        self.assertIn('\\u', stream.getvalue())

    def folders(self):
        home = self.root / 'home'
        paths = dict(zip(smoke.FOLDERS.values(), (home / 'Desktop', home / 'Documents', home / 'Downloads')))
        for path in paths.values():
            path.mkdir(parents=True)
        return home, paths

    def test_03_folders_pass_with_actual_jarvis_candidate_definition(self):
        home, paths = self.folders()
        with patch.object(smoke.Path, 'home', return_value=home), patch.object(smoke, 'known_folder', side_effect=paths.__getitem__):
            self.assertEqual(self.checked(smoke.check_folders)[0], smoke.PASS)

    def test_03_windows_api_failure_isolated(self):
        with patch.object(smoke, 'known_folder', side_effect=OSError(SECRET)):
            self.assertEqual(self.checked(smoke.check_folders)[0], smoke.FAIL)

    def test_03_onedrive_redirection_mismatch_warns_without_user_paths(self):
        home, paths = self.folders()
        paths[next(iter(smoke.FOLDERS.values()))] = home / ('OneDrive - ' + SECRET) / 'Desktop'
        with patch.object(smoke.Path, 'home', return_value=home), patch.object(smoke, 'known_folder', side_effect=paths.__getitem__):
            state, reason = self.checked(smoke.check_folders)
        self.assertEqual(state, smoke.WARN)
        self.assertIn('OneDrive var', reason)

    def test_03_missing_module_and_changed_helper_are_skipped(self):
        path = self.repo / 'modules/files.py'
        self.write(path, 'def folder_path(candidates):\n    raise RuntimeError("must not run")\n')
        with patch.object(smoke, 'known_folder', return_value=Path('dummy')):
            self.assertEqual(self.checked(smoke.check_folders)[0], smoke.SKIP)
            path.unlink()
            self.assertIn('modül yok', self.checked(smoke.check_folders)[1])

    def test_03_native_api_signature_and_memory_release_mocked_on_linux(self):
        buffer = ctypes.create_unicode_buffer('C:\\Users\\Test\\Desktop')
        def query(guid, flags, token, output):
            self.assertEqual(flags, 0x4000)
            self.assertIsNone(token)
            ctypes.cast(output, ctypes.POINTER(ctypes.c_wchar_p))[0] = ctypes.cast(buffer, ctypes.c_wchar_p)
            return 0
        shell, ole = Mock(), Mock()
        shell.SHGetKnownFolderPath.side_effect = query
        with patch.object(smoke.ctypes, 'WinDLL', side_effect=[shell, ole], create=True):
            self.assertEqual(str(smoke.known_folder(next(iter(smoke.FOLDERS.values())))), buffer.value)
        ole.CoTaskMemFree.assert_called_once()
        shell.SHGetKnownFolderPath.return_value = -1
        shell.SHGetKnownFolderPath.side_effect = None
        with patch.object(smoke.ctypes, 'WinDLL', side_effect=[shell, ole], create=True):
            with self.assertRaises(OSError):
                smoke.known_folder(next(iter(smoke.FOLDERS.values())))

    def test_04_permissions_pass_without_writing_application_data(self):
        with patch.object(smoke.os, 'access', return_value=True):
            self.assertEqual(self.checked(smoke.check_writable)[0], smoke.PASS)

    def test_04_permissions_fail(self):
        with patch.object(smoke.os, 'access', return_value=False):
            self.assertEqual(self.checked(smoke.check_writable)[0], smoke.FAIL)

    def test_04_missing_profile_warns_and_is_not_created(self):
        path = self.data / 'users/hamdi.json'
        path.unlink()
        self.assertEqual(self.checked(smoke.check_writable)[0], smoke.WARN)
        self.assertFalse(path.exists())

    def test_05_google_pass_scopes_and_expiry_without_secrets(self):
        self.token()
        state, reason = self.checked(smoke.check_google)
        self.assertEqual(state, smoke.PASS)
        self.assertIn('Gmail okuma', reason)
        self.assertIn('süresi dolmuş: 0', reason)

    def test_05_google_fail_malformed_and_unreadable(self):
        path = self.token()
        self.write(path, '{' + SECRET)
        self.assertEqual(self.checked(smoke.check_google)[0], smoke.FAIL)
        self.token(token=123)
        self.assertEqual(self.checked(smoke.check_google)[0], smoke.FAIL)
        with patch.object(smoke, 'small_read', side_effect=PermissionError(SECRET)):
            self.assertEqual(self.checked(smoke.check_google)[0], smoke.FAIL)

    def test_05_expired_unknown_scopes_and_legacy_warn_without_echo(self):
        self.token(expiry='2026-10-17T00:00:00Z', scopes=[SECRET])
        self.assertEqual(self.checked(smoke.check_google)[0], smoke.WARN)
        path = self.data / 'google_users/hamdi/google_token.json'
        raw = path.read_text(encoding='utf-8')
        path.unlink()
        self.write(self.data / 'google_token.json', raw)
        self.assertIn('Eski ortak', self.checked(smoke.check_google)[1])

    def test_05_missing_token_warns_and_is_not_created(self):
        self.assertEqual(self.checked(smoke.check_google)[0], smoke.WARN)
        self.assertFalse((self.data / 'google_users').exists())

    def test_06_outlook_registry_pass_without_com_activation(self):
        self.registry.values['CR', r'Outlook.Application\CLSID', ''] = '{0006F03A-0000-0000-C000-000000000046}'
        self.assertEqual(self.checked(smoke.check_outlook)[0], smoke.PASS)
        self.assertTrue(all(call.args[3] & self.registry.KEY_READ for call in self.registry.OpenKey.call_args_list))

    def test_06_outlook_fail_unreadable_registry(self):
        self.registry.OpenKey.side_effect = PermissionError(SECRET)
        self.assertEqual(self.checked(smoke.check_outlook)[0], smoke.FAIL)

    def test_06_outlook_missing_warns_invalid_clsid_fails(self):
        self.assertEqual(self.checked(smoke.check_outlook)[0], smoke.WARN)
        self.registry.values['CR', r'Outlook.Application\CLSID', ''] = SECRET
        self.assertEqual(self.checked(smoke.check_outlook)[0], smoke.FAIL)

    def audio(self, devices=None):
        module = types.ModuleType('sounddevice')
        module.query_devices = Mock(return_value=devices if devices is not None else [
            {'name': SECRET, 'max_input_channels': 1, 'max_output_channels': 0},
            {'name': SECRET, 'max_input_channels': 0, 'max_output_channels': 2}])
        return module

    def test_07_audio_pass_enumeration_only(self):
        module = self.audio()
        with patch.dict(sys.modules, {'sounddevice': module}):
            self.assertEqual(self.checked(smoke.check_audio)[0], smoke.PASS)
        module.query_devices.assert_called_once_with()

    def test_07_audio_fail_no_input_or_output(self):
        with patch.dict(sys.modules, {'sounddevice': self.audio([])}):
            self.assertEqual(self.checked(smoke.check_audio)[0], smoke.FAIL)

    def test_07_audio_privacy_denial_and_unknown_are_not_reported_as_pass(self):
        key = ('LM', r'Software\Policies\Microsoft\Windows\AppPrivacy', 'LetAppsAccessMicrophone')
        self.registry.values[key] = 2
        with patch.dict(sys.modules, {'sounddevice': self.audio()}):
            self.assertEqual(self.checked(smoke.check_audio)[0], smoke.FAIL)
            self.registry.values.clear()
            self.assertEqual(self.checked(smoke.check_audio)[0], smoke.WARN)

    def test_07_missing_device_module_is_skipped(self):
        with patch.dict(sys.modules, {'sounddevice': None}):
            self.assertEqual(self.checked(smoke.check_audio)[0], smoke.SKIP)

    def http(self, status=200, raw=b'{"version":"0.12.0"}'):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = raw
        return connection

    def test_08_ollama_pass_only_fixed_loopback_get_no_proxy_or_model(self):
        connection = self.http()
        with patch.object(smoke.http.client, 'HTTPConnection', return_value=connection) as constructor:
            self.assertEqual(self.checked(smoke.check_ollama)[0], smoke.PASS)
        constructor.assert_called_once_with('127.0.0.1', 11434, timeout=2)
        connection.request.assert_called_once_with('GET', '/api/version')
        connection.close.assert_called_once()

    def test_08_ollama_fail_timeout_no_exception_detail(self):
        connection = self.http()
        connection.request.side_effect = TimeoutError(SECRET)
        with patch.object(smoke.http.client, 'HTTPConnection', return_value=connection):
            self.assertEqual(self.checked(smoke.check_ollama)[0], smoke.FAIL)
        connection.close.assert_called_once()

    def test_08_ollama_connection_refused_warns_and_cli_exits_zero(self):
        connection = self.http()
        connection.request.side_effect = ConnectionRefusedError(SECRET)
        with patch.object(smoke.http.client, 'HTTPConnection', return_value=connection):
            self.assertEqual(self.checked(smoke.check_ollama)[0], smoke.WARN)
            with patch.object(smoke, 'CHECKS', (('Ollama', smoke.check_ollama),)), \
                    patch.object(smoke.sys, 'stdout', io.StringIO()):
                code = smoke.main(['--rapor-klasoru', str(self.reports), '--profil', 'hamdi'])
        self.assertEqual(code, 0)
        report = next(self.reports.glob('duman_raporu_*')).read_text(encoding='utf-8')
        self.assertIn('UYARI', report)
        self.assertNotIn(SECRET, report)

    def test_default_reports_follow_data_directory_outside_repository(self):
        home = self.root / 'home'
        for mode in ('home', 'environment', 'argument'):
            with self.subTest(mode=mode):
                data = home / '.jarvis' if mode == 'home' else self.data / mode
                args = ['--profil', 'hamdi']
                if mode == 'argument':
                    args += ['--veri-klasoru', str(data)]
                with patch.object(smoke, '__file__', str(self.repo / 'scripts/pc_duman_testi.py')), \
                        patch.object(smoke.Path, 'home', return_value=home), \
                        patch.dict(os.environ, {'JARVIS_DATA_DIR': str(data) if mode == 'environment' else ''}), \
                        patch.object(smoke, 'CHECKS', (('deneme', lambda ctx: (smoke.PASS, 'tamam')),)), \
                        patch.object(smoke.sys, 'stdout', io.StringIO()):
                    self.assertEqual(smoke.main(args), 0)
                reports = list((data / 'duman_raporlari').glob('duman_raporu_*.txt'))
                self.assertEqual(len(reports), 1)
                self.assertFalse(reports[0].is_relative_to(self.repo))
                self.assertEqual(list(self.repo.rglob('duman_raporu_*.txt')), [])

    def test_08_ollama_redirect_invalid_json_or_oversized_response_fails(self):
        for status, raw in ((302, b'{}'), (200, b'bad'), (200, b'x' * 4097), (200, b'{}')):
            with self.subTest(status=status, length=len(raw)):
                connection = self.http(status, raw)
                with patch.object(smoke.http.client, 'HTTPConnection', return_value=connection):
                    self.assertEqual(self.checked(smoke.check_ollama)[0], smoke.FAIL)
                self.assertEqual(connection.request.call_count, 1)

    def test_09_quota_pass_counts_today_and_archives_in_istanbul_time(self):
        self.quota()
        self.quota(self.data / 'kota/hamdi.jsonl.archive-a', t='2026-10-17T22:05:00+00:00')
        state, reason = self.checked(smoke.check_quota)
        self.assertEqual(state, smoke.PASS)
        self.assertIn('çağrı: 2', reason)

    def test_09_quota_fail_unreadable(self):
        self.quota()
        with patch.object(smoke, 'small_read', side_effect=PermissionError(SECRET)):
            self.assertEqual(self.checked(smoke.check_quota)[0], smoke.FAIL)

    def test_09_quota_absent_or_partial_warns(self):
        self.assertEqual(self.checked(smoke.check_quota)[0], smoke.WARN)
        self.assertFalse((self.data / 'kota').exists())
        self.quota(self.data / 'kota/hamdi.jsonl.1')
        self.assertEqual(self.checked(smoke.check_quota)[0], smoke.WARN)
        self.quota()
        with (self.data / 'kota/hamdi.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(SECRET)
        self.assertIn('bozuk satır: 1', self.checked(smoke.check_quota)[1])

    def test_10_log_pass_ignores_errors_before_last_200_lines(self):
        self.write(self.data / 'jarvis.log', '2026-10-18 01:00:00 ERROR ' + SECRET + '\n'
                   + ('2026-10-18 12:00:00 INFO ' + SECRET + '\n') * 200)
        state, reason = self.checked(smoke.check_log)
        self.assertEqual(state, smoke.PASS)
        self.assertIn('hata 0, uyarı 0', reason)

    def test_10_log_fail_unreadable(self):
        self.write(self.data / 'jarvis.log', SECRET)
        with patch.object(smoke.Path, 'open', side_effect=PermissionError(SECRET)):
            self.assertEqual(self.checked(smoke.check_log)[0], smoke.FAIL)

    def test_10_log_counts_levels_and_allowlisted_types_without_contents(self):
        self.write(self.data / 'jarvis.log', '2026-10-18 12:00:00 ERROR ' + SECRET + ' ValueError\n'
                   + '2026-10-18 12:00:00 WARNING ' + SECRET + '\n'
                   + '2026-10-18 12:00:00 CRITICAL ' + SECRET + ' TimeoutError\n')
        state, reason = self.checked(smoke.check_log)
        self.assertEqual(state, smoke.WARN)
        self.assertIn('hata 2, uyarı 1', reason)
        self.assertIn('ValueError 1', reason)

    def test_10_damaged_log_encoding_warns_without_echo(self):
        (self.data / 'jarvis.log').write_bytes(b'\xff\xfe' + SECRET.encode())
        state, reason = self.checked(smoke.check_log)
        self.assertEqual(state, smoke.WARN)
        self.assertIn('kodlaması bozuk', reason)

    def test_linux_skips_every_windows_check_without_touching_apis(self):
        self.ctx.windows = False
        with patch.object(smoke, 'known_folder', side_effect=AssertionError('Windows API')), \
                patch.object(smoke, 'registry_value', side_effect=AssertionError('registry')), \
                patch.object(smoke.importlib, 'import_module', side_effect=AssertionError('device import')):
            for check in (smoke.check_folders, smoke.check_outlook, smoke.check_audio):
                self.assertEqual(self.checked(check)[0], smoke.SKIP)

    def test_missing_repository_modules_skip_explicitly(self):
        for relative, check in (('config.py', smoke.check_writable), ('modules/google_api.py', smoke.check_google),
                                ('modules/usage_meter.py', smoke.check_quota), ('modules/engine_runtime.py', smoke.check_log)):
            (self.repo / relative).unlink()
            state, reason = self.checked(check)
            self.assertEqual(state, smoke.SKIP)
            self.assertIn('modül yok: ' + relative, reason)

    def test_crash_does_not_stop_later_checks_or_leak_message(self):
        with patch.object(smoke, 'CHECKS', (('hata', Mock(side_effect=RuntimeError(SECRET))),
                                           ('sonraki', lambda ctx: (smoke.PASS, 'tamam')))):
            rows = smoke.run_checks(self.ctx)
        self.assertEqual([r[1] for r in rows], [smoke.FAIL, smoke.PASS])
        self.assertNotIn(SECRET, smoke.summary(rows, self.ctx.now))

    def test_cli_linux_report_and_application_files_unchanged(self):
        self.token()
        self.quota()
        self.write(self.data / 'jarvis.log', '2026-10-18 12:00:00 INFO ' + SECRET)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        output = io.StringIO()
        with patch.object(smoke, '__file__', str(self.repo / 'scripts/pc_duman_testi.py')), \
                patch.object(smoke.sys, 'platform', 'linux'), patch.object(smoke.sys, 'version_info', (3, 13)), \
                patch.object(smoke.sys, 'stdout', output), patch.object(smoke.metadata, 'version', return_value='1.0'), \
                patch.object(smoke, 'ollama_version', return_value=True), \
                patch.dict(sys.modules, {'config': None, 'modules.google_api': None, 'modules.usage_meter': None}):
            code = smoke.main(['--veri-klasoru', str(self.data), '--rapor-klasoru', str(self.reports), '--profil', 'hamdi'])
        self.assertEqual(code, 0)
        reports = list(self.reports.glob('duman_raporu_*.txt'))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text(encoding='utf-8')
        self.assertEqual(report.count(': ATLANDI'), 3)
        self.assertEqual(len(report.splitlines()), 13)
        self.assertNotIn(SECRET, report + output.getvalue())
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p not in reports}
        self.assertEqual(before, after)
        self.assertEqual(list(self.reports.glob('kodlama_*')), [])

    def test_cli_unreadable_profile_does_not_abort_other_checks(self):
        self.write(self.data / 'active_user.txt', 'x' * 1025)
        with patch.object(smoke, '__file__', str(self.repo / 'scripts/pc_duman_testi.py')), \
                patch.object(smoke, 'ollama_version', return_value=False), \
                patch.object(smoke.sys, 'platform', 'linux'), patch.object(smoke.sys, 'stdout', io.StringIO()):
            code = smoke.main(['--veri-klasoru', str(self.data), '--rapor-klasoru', str(self.reports)])
        self.assertEqual(code, 1)
        report = next(self.reports.glob('duman_raporu_*')).read_text(encoding='utf-8')
        self.assertIn('Aktif profil okunamadı', report)
        self.assertIn('10. Günlük:', report)

    def test_profile_slug_matches_personalization_and_prevents_traversal(self):
        self.write(self.data / 'active_user.txt', 'Şeyma İĞDE')
        self.assertEqual(smoke.active_profile(self.repo, self.data), 'seymaigde')
        with self.assertRaises(SystemExit), patch.object(smoke.sys, 'stderr', io.StringIO()):
            smoke.main(['--profil', '../secret'])

    def test_main_report_write_failure_returns_two_without_secret_detail(self):
        output = io.StringIO()
        with patch.object(smoke, 'CHECKS', (('x', lambda ctx: (smoke.PASS, 'tamam')),)), \
                patch.object(smoke.sys, 'stdout', output), \
                patch.object(smoke.Path, 'open', side_effect=PermissionError(SECRET)):
            code = smoke.main(['--rapor-klasoru', str(self.reports), '--profil', 'hamdi'])
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET, output.getvalue())

    def test_subprocess_audit_forbids_writes_outside_reports_and_any_process_or_network(self):
        # The hook lives only in the child, so it cannot affect other CI tests.
        code = r'''
import importlib.util, os, pathlib, sys
source, data, reports = map(pathlib.Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location('audit_smoke', source)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.metadata.version = lambda name: '1.0'
module.ollama_version = lambda: True
module.sys.platform = 'linux'
reports = reports.resolve()
def guard(event, args):
    if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect'):
        raise AssertionError('unexpected process/network')
    if event == 'open' and not isinstance(args[0], int):
        flags = args[2] or 0
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            path = pathlib.Path(args[0]).resolve()
            # NamedTemporaryFile audits its directory before its custom opener;
            # the actual created filename receives a separate guarded event.
            if path != reports:
                assert path.parent == reports, 'write outside report directory'
                assert path.name.startswith(('duman_raporu_', 'kodlama_')), 'unexpected output'
    if event == 'os.mkdir':
        assert pathlib.Path(args[0]).resolve() == reports, 'application directory created'
    if event == 'os.remove':
        path = pathlib.Path(args[0]).resolve()
        assert path.parent == reports and path.name.startswith('kodlama_'), 'application file deleted'
    if event in ('os.rename', 'os.rmdir'):
        raise AssertionError('unexpected move/removal')
sys.addaudithook(guard)
raise SystemExit(module.main(['--veri-klasoru', str(data), '--rapor-klasoru', str(reports), '--profil', 'hamdi']))
'''
        environment = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-c', code, str(Path(SPEC.origin)),
                                 str(self.data), str(self.reports)], capture_output=True,
                                text=True, encoding='utf-8', env=environment, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(list(self.reports.glob('duman_raporu_*.txt'))), 1)


if __name__ == '__main__':
    unittest.main()
