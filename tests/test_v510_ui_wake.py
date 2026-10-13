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
        live = Path('modules/live.py').read_text(encoding='utf-8')
        self.assertIn('3: 0.18', ww)
        self.assertIn('soft_hits', ww)
        self.assertIn('self._wake_soft_hits', live)
        self.assertIn('AGC_TARGET = 1250', live)
        self.assertIn('AGC_MAX = 9.0', live)


if __name__ == '__main__':
    unittest.main()
