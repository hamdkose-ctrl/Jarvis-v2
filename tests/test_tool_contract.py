import importlib
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch


class ToolContractTests(unittest.TestCase):
    def setUp(self):
        try:
            from modules import tool_contract as contract
        except ImportError:
            contract = None
        self.contract = contract

    @staticmethod
    def sample(**changes):
        data = {
            'id': 'yazici',
            'name': '3D yazıcı',
            'area': 'cihaz',
            'icon': 'gear',
            'actions': [{
                'id': 'gonder', 'name': 'Baskıyı gönder', 'desc': 'Dosyayı cihaza yollar.',
                'class': 'local_destructive', 'params': {'dosya': 'str'},
            }],
            'status': lambda: {'state': 'ready', 'detail': 'Hazır'},
            'cancel': lambda: None,
        }
        data.update(changes)
        return data

    def require(self):
        self.assertIsNotNone(self.contract, 'modules.tool_contract henüz yok')
        return self.contract

    def test_validate_accepts_contract_and_all_permission_classes(self):
        c = self.require()
        from modules.permission_gate import CLASSES
        self.assertEqual(c.validate(self.sample()), [])
        for action_class in CLASSES:
            with self.subTest(action_class=action_class):
                row = self.sample(actions=[{
                    'id': 'islem', 'name': 'İşlem', 'desc': 'Açıklama',
                    'class': action_class, 'params': {'a': 'str', 'b': 'int', 'c': 'float', 'd': 'bool'},
                }])
                self.assertEqual(c.validate(row), [])

    def test_validate_returns_errors_instead_of_crashing(self):
        c = self.require()
        bad_rows = [
            None, [], 'bad',
            self.sample(id='UPPER'), self.sample(id='x' * 41), self.sample(name=''),
            self.sample(actions=[]), self.sample(status=None), self.sample(cancel='no'),
            self.sample(actions=[{'id': 'x', 'name': 'X', 'desc': 'd', 'class': 'invented', 'params': {}}]),
            self.sample(actions=[{'id': 'x', 'name': 'X', 'desc': 'd', 'class': 'read', 'params': {'x': 'bytes'}}]),
            self.sample(name='n' * 201), self.sample(area='a' * 201),
            self.sample(actions=[{'id': 'x', 'name': 'X', 'desc': 'd' * 201, 'class': 'read', 'params': {}}]),
        ]
        for row in bad_rows:
            with self.subTest(row=repr(row)[:80]):
                errors = c.validate(row)
                self.assertIsInstance(errors, list)
                self.assertTrue(errors)
                self.assertTrue(all(isinstance(item, str) for item in errors))

    def test_describe_is_json_compatible_calls_status_and_handles_status_error(self):
        c = self.require()
        called = []
        row = self.sample(status=lambda: called.append('status') or {'state': 'running', 'detail': 'Baskı sürüyor'})
        described = c.describe(row)
        self.assertEqual(called, ['status'])
        self.assertEqual(described['status'], {'state': 'running', 'detail': 'Baskı sürüyor'})
        self.assertNotIn('cancel', described)
        json.dumps(described, ensure_ascii=False)

        def broken():
            raise RuntimeError('offline')
        described = c.describe(self.sample(status=broken))
        self.assertEqual(described['status']['state'], 'error')
        self.assertIsInstance(described['status']['detail'], str)
        json.dumps(described, ensure_ascii=False)

    def test_load_all_temp_package_loads_valid_skips_invalid_and_duplicate_ids(self):
        c = self.require()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / 'fake_tools'
            pkg.mkdir()
            (pkg / '__init__.py').write_text('', encoding='utf-8')
            (pkg / 'tool_fake.py').write_text(textwrap.dedent('''
                cancelled = []
                def status(): return {'state': 'ready', 'detail': 'Sahte hazır'}
                def cancel(): cancelled.append(True)
                CONTRACT = {
                    'id': 'fake', 'name': 'Sahte araç', 'area': 'test', 'icon': 'gear',
                    'actions': [{'id': 'run', 'name': 'Çalıştır', 'desc': 'Sahte işlem', 'class': 'read', 'params': {'q': 'str'}}],
                    'status': status, 'cancel': cancel,
                }
            '''), encoding='utf-8')
            (pkg / 'tool_bad.py').write_text("CONTRACT = {'id': 'BAD'}\n", encoding='utf-8')
            for name in ('tool_dup_a.py', 'tool_dup_b.py'):
                (pkg / name).write_text(textwrap.dedent('''
                    def status(): return {'state': 'ready', 'detail': 'ok'}
                    def cancel(): pass
                    CONTRACT = {'id': 'dup', 'name': 'Duplicate', 'area': 'test', 'icon': 'gear',
                                'actions': [{'id': 'x', 'name': 'X', 'desc': 'x', 'class': 'read', 'params': {}}],
                                'status': status, 'cancel': cancel}
                '''), encoding='utf-8')
            sys.path.insert(0, tmp)
            importlib.invalidate_caches()
            try:
                with patch.object(c, '_record_failure') as failure:
                    loaded = c.load_all('fake_tools')
                self.assertEqual(set(loaded), {'fake'})
                self.assertGreaterEqual(failure.call_count, 3)
                shown = c.describe(loaded['fake'])
                self.assertEqual(shown['status']['state'], 'ready')
                loaded['fake']['cancel']()
                module = importlib.import_module('fake_tools.tool_fake')
                self.assertEqual(module.cancelled, [True])
            finally:
                sys.path.remove(tmp)
                for key in list(sys.modules):
                    if key == 'fake_tools' or key.startswith('fake_tools.'):
                        sys.modules.pop(key, None)
                importlib.invalidate_caches()

    def test_load_all_bad_package_or_import_error_does_not_crash_other_tools(self):
        c = self.require()
        self.assertEqual(c.load_all('package_that_does_not_exist_jarvis'), {})
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / 'mixed_tools'; pkg.mkdir(); (pkg / '__init__.py').write_text('')
            (pkg / 'tool_boom.py').write_text("raise RuntimeError('boom')\n")
            (pkg / 'tool_ok.py').write_text(textwrap.dedent('''
                def status(): return {'state': 'not_connected', 'detail': 'Bağlı değil'}
                def cancel(): pass
                CONTRACT = {'id': 'ok', 'name': 'OK', 'area': 'test', 'icon': 'gear',
                            'actions': [{'id': 'x', 'name': 'X', 'desc': 'x', 'class': 'read', 'params': {}}],
                            'status': status, 'cancel': cancel}
            '''))
            sys.path.insert(0, tmp); importlib.invalidate_caches()
            try:
                with patch.object(c, '_record_failure') as failure:
                    loaded = c.load_all('mixed_tools')
                self.assertEqual(set(loaded), {'ok'})
                self.assertTrue(failure.called)
            finally:
                sys.path.remove(tmp)
                for key in list(sys.modules):
                    if key == 'mixed_tools' or key.startswith('mixed_tools.'):
                        sys.modules.pop(key, None)


if __name__ == '__main__':
    unittest.main()
