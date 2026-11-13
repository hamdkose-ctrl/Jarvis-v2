import unittest
from pathlib import Path


class V510UiWakeTests(unittest.TestCase):
    def test_github_publish_button_and_backend_exist(self):
        ui = Path('webui/nx.js').read_text(encoding='utf-8')
        web = Path('web.py').read_text(encoding='utf-8')
        self.assertIn('data-act="ghpublish"', ui)
        self.assertIn("api('github_publish')", ui)
        self.assertIn('def github_publish(self)', web)
        self.assertIn('publish_worktree', web)

    def test_github_ui_requires_explicit_upload(self):
        ui = Path('webui/nx.js').read_text(encoding='utf-8')
        self.assertNotIn('Testten geçen değişiklik GitHub ana dalına güvenli commit olarak gönderilir', ui)
        self.assertIn('GitHub’a Yükle', ui)

    def test_far_field_wake_tuning(self):
        ww = Path('modules/wakeword.py').read_text(encoding='utf-8')
        self.assertIn('3: 0.18', ww)
        self.assertIn('soft_hits', ww)

    def test_wake_beep_switch_has_a_real_consumer(self):
        # 'Uyanma sesi' sürgüsü eskiden hiçbir tüketicisi olmayan live_beep anahtarına yazıyordu.
        # Artık anahtar wake_beep'tir ve uyanma bip'i gerçekten ona uyar; varsayılan açıktır.
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from modules import wakeword

        beeps = []
        winsound = SimpleNamespace(Beep=lambda freq, ms: beeps.append((freq, ms)))
        for stored, expected in ((False, 0), (None, 1), (True, 1)):
            with self.subTest(wake_beep=stored):
                beeps.clear()
                settings = {} if stored is None else {'wake_beep': stored}
                with patch.dict(sys.modules, {'winsound': winsound}), \
                     patch.object(wakeword, 'load_settings', return_value=settings):
                    wakeword._beep()
                self.assertEqual(len(beeps), expected)

    def test_no_inert_wake_sound_switch_is_offered(self):
        ui = Path('webui/nx.js').read_text(encoding='utf-8')
        self.assertIn("sw('wake_beep',u.wake_beep)", ui)
        self.assertNotIn('live_beep', ui)
        api = Path('modules/nxapi.py').read_text(encoding='utf-8')
        self.assertIn('out["wake_beep"]', api)
        self.assertIn('"wake_beep"', api[api.index('def ui_set'):api.index('def ui_set') + 1400])

    def test_ui_switch_writes_the_key_the_beep_reads(self):
        from unittest.mock import patch
        from modules import nxapi
        with patch('modules.nxapi.save_settings') as save:
            nxapi.ui_set('wake_beep', False)
        self.assertEqual(save.call_args.kwargs, {'wake_beep': False})


if __name__ == '__main__':
    unittest.main()
