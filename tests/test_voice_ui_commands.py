import unittest
from unittest.mock import Mock


class VoiceUiCommandsTests(unittest.TestCase):
    def test_every_settings_section_and_menu_opens_by_voice(self):
        from modules import selfctl
        cases = {
            'menüyü aç': 'menu|', 'menü sayfasını aç': 'menu|', 'github sayfasını aç': 'settings|github',
            'github ayarlarını aç': 'settings|github', 'güncelleme sayfasını aç': 'settings|github',
            'telefon ve mesajlar sayfasını aç': 'settings|iletisim', 'ekran ve dosyalar bölümünü aç': 'settings|ekran',
            'kamera ayarlarını aç': 'settings|ekran', 'hesap sayfasını aç': 'settings|kullanici',
            'yapay zekâ sayfasını aç': 'settings|ai', 'ses ayarlarını aç': 'settings|ses',
            'hafıza sayfasını aç': 'settings|hafiza', 'telefon ayarlarını aç': 'tools|telefon', 'çalışma sayfasını aç': 'study|',
            'sohbet sayfasını aç': 'chat|', 'ana ekranı aç': 'home|', 'görevler sayfasını aç': 'tools|takvim',
        }
        for command, target in cases.items():
            with self.subTest(command=command):
                emit = Mock()
                self.assertIsNotNone(selfctl.handle(command, emit))
                emit.assert_called_once_with('nav', target)

    def test_calculator_and_other_apps_are_not_mistaken_for_jarvis_pages(self):
        from modules import selfctl
        for command in ('hesap makinesini aç', 'hesap makinesi aç', 'müziği tekrar oynat', 'şarkıyı yeniden oynat'):
            with self.subTest(command=command):
                emit = Mock()
                self.assertIsNone(selfctl.handle(command, emit))
                emit.assert_not_called()

    def test_hologram_look_commands_send_only_whitelisted_ui_events(self):
        from modules import selfctl
        cases = {
            'hologramı turkuaz yap': 'hologramtone|turquoise', 'silüet rengini sarı yap': 'hologramtone|yellow',
            'hologram rengi mavi olsun': 'hologramtone|blue', 'lav dağlarını seç': 'hologrambg|lava',
            'arka planı mavi dağlar yap': 'hologrambg|mountains', 'açılış animasyonunu tekrar oynat': 'bustreplay|',
            'ana ekran animasyonunu kapat': 'nxbust|0', 'ana ekran animasyonunu aç': 'nxbust|1',
        }
        for command, payload in cases.items():
            with self.subTest(command=command):
                emit = Mock()
                self.assertIsNotNone(selfctl.handle(command, emit))
                emit.assert_called_once_with('ui', payload)

    def test_ui_commands_never_touch_models_keys_or_settings_files(self):
        from unittest.mock import patch
        from modules import selfctl
        with patch.object(selfctl, 'save_settings') as save:
            selfctl.handle('hologramı sarı yap', Mock())
            selfctl.handle('lav dağlarını seç', Mock())
        save.assert_not_called()


class KnowledgeAndGithubVoiceTests(unittest.TestCase):
    def test_catalog_has_safe_kb_and_github_read_actions_with_confirmation_where_needed(self):
        from modules import app_actions
        acts = app_actions._ACTIONS
        for name in ('github_verify', 'update_now', 'kb_add_path'):
            self.assertFalse(acts[name]['confirm'], name)
        for name in ('kb_remove', 'kb_clear'):
            self.assertTrue(acts[name]['confirm'], name)

    def test_publishing_pulling_phone_access_and_key_actions_stay_out_of_voice_catalog(self):
        from modules import app_actions
        for name in ('github_publish', 'github_pull', 'github_backup_pull', 'phone_toggle', 'phone_info', 'update_token_save',
                     'llm_validate', 'smart_router_save'):
            self.assertNotIn(name, app_actions._ACTIONS, name)

    def test_kb_remove_rejects_unknown_document_and_confirms_known_one(self):
        from types import SimpleNamespace
        from modules import app_actions
        profile = SimpleNamespace(data={'kb': [{'id': 7}]})
        with self.assertRaises(ValueError):
            app_actions._check_reference(profile, 'kb_remove', {'did': 99})
        app_actions._check_reference(profile, 'kb_remove', {'did': 7})
        spec, values = app_actions.validate('kb_remove', {'did': 7})
        self.assertTrue(spec['confirm'])
        self.assertEqual(values, {'did': 7})


if __name__ == '__main__':
    unittest.main()
