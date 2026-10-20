"""Dosya ve kayıtlı PC işlemleri: izin kararı işlemden önce uygulanır."""
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
from tests import test_file_ops as file_fixture
from tests import test_verified_execution as pc_fixture
from modules import file_ops, llm, pc_contracts, permission_audit, permission_policy, requests_state

system_control = pc_fixture.pc


class FileSystemGateTests(unittest.TestCase):
    write = file_fixture.FileOpsTests.write

    def setUp(self):
        file_fixture.FileOpsTests.setUp(self)
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        token = requests_state._current.set(None); self.addCleanup(requests_state._current.reset, token)
        self.enterContext(patch.object(permission_policy, 'ROOT', self.home / 'policy'))
        self.enterContext(patch.object(permission_audit, 'DATA_DIR', self.home))
        self.enterContext(patch.object(pc_contracts, 'ROOT', self.home / 'pc'))
        self.endpoint = Mock(GetMute=Mock(return_value=0))
        self.enterContext(patch.object(system_control, '_volume_endpoint', return_value=self.endpoint))

    def deny(self, via):
        permission_policy.set('alice', via, 'local_reversible', 'deny')

    def test_denied_file_move_keeps_source_and_audits_final_deny(self):
        source = self.write(self.downloads, 'rapor.txt')
        self.deny('file')
        reply = file_ops.handle('rapor dosyasını belgelere taşı', 'alice')
        self.assertIn('Engelle', reply)
        self.assertTrue(source.exists())
        self.assertFalse((self.documents / 'rapor.txt').exists())
        row = permission_audit.recent('alice')[0]
        self.assertEqual((row['via'], row['decision']), ('file', 'deny'))

    def test_deny_covers_rename_create_and_undo(self):
        source = self.write(self.desktop, 'eski.txt')
        file_ops.handle('masaüstüne yeni adında bir metin dosyası oluştur', 'alice')
        self.deny('file')
        for command in ('eski dosyasının adını baska yap',
                        'masaüstüne kapali adında bir metin dosyası oluştur',
                        'son dosya işlemini geri al'):
            self.assertIn('Engelle', file_ops.handle(command, 'alice'))
        self.assertTrue(source.exists())
        self.assertTrue((self.desktop / 'yeni.txt').exists())
        self.assertFalse((self.desktop / 'kapali.txt').exists())
        permission_policy.set('alice', 'file', 'local_reversible', 'ask')
        self.assertIn('geri aldım', file_ops.handle('son dosya işlemini geri al', 'alice'))
        self.assertFalse((self.desktop / 'yeni.txt').exists())

    def test_file_policy_failure_is_closed(self):
        source = self.write(self.downloads, 'rapor.txt')
        with patch.object(permission_policy, 'apply', side_effect=RuntimeError('failure')), \
                patch.object(file_ops, '_record_failure', create=True) as record:
            file_ops.handle('rapor dosyasını belgelere taşı', 'alice')
        self.assertTrue(source.exists())
        record.assert_called_once()

    def test_system_deny_precedes_target_and_final_audit(self):
        self.deny('system')
        with self.assertRaises(PermissionError):
            system_control.set_volume(30)
        self.endpoint.SetMasterVolumeLevelScalar.assert_not_called()
        row = permission_audit.recent('alice')[0]
        self.assertEqual((row['via'], row['decision']), ('system', 'deny'))

    def test_unknown_name_preserves_existing_reversible_policy(self):
        with patch('modules.permission_classify.classify_detail', return_value=('system_config', False)):
            self.assertTrue(system_control.set_volume(30))
        self.endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(0.3, None)

    def test_recognized_system_setting_asks_and_policy_cannot_unlock_it(self):
        with patch('modules.permission_classify.classify_detail', return_value=('system_config', True)):
            with self.assertRaises(PermissionError):
                system_control.set_volume(30)
        self.endpoint.SetMasterVolumeLevelScalar.assert_not_called()

    def test_system_gate_failure_and_wrong_owner_are_closed(self):
        with patch.object(permission_policy, 'apply', side_effect=RuntimeError('failure')), \
                patch.object(system_control, '_record_failure') as record:
            with self.assertRaises(PermissionError):
                system_control.set_volume(30)
            record.assert_called_once()
        token = requests_state._current.set(('bob', 'request'))
        try:
            with self.assertRaises(PermissionError):
                system_control.set_volume(30)
        finally:
            requests_state._current.reset(token)
        self.endpoint.SetMasterVolumeLevelScalar.assert_not_called()

    def test_extra_system_entry_points_are_denied_before_native_calls(self):
        self.deny('system')
        with patch.object(system_control, 'set_mute') as mute, \
                patch.object(system_control.pyautogui, 'press') as press, \
                patch('webbrowser.open_new_tab') as tab, \
                patch.object(system_control.os, 'startfile', create=True) as start:
            for invoke in (system_control.mute_volume, system_control.open_new_tab,
                           lambda: system_control.windows_settings('wifi ayarlarını aç')):
                with self.assertRaises(PermissionError):
                    invoke()
            for target in (mute, press, tab, start):
                target.assert_not_called()
            # Komut Windows ayarı değilse bu yolun politikası sohbeti engellemez.
            self.assertIsNone(system_control.windows_settings('merhaba'))

    def test_absent_actor_cannot_modify_file_or_system(self):
        source = self.write(self.downloads, 'rapor.txt')
        token = llm._key_context.set(None)
        try:
            with self.assertRaises(PermissionError):
                system_control.set_volume(30)
            file_ops.handle('rapor dosyasını belgelere taşı')
        finally:
            llm._key_context.reset(token)
        self.assertTrue(source.exists())
        self.endpoint.SetMasterVolumeLevelScalar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
