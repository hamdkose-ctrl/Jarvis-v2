"""Masaüstü maskot tıklama geçişi ayarı: `mascot_click_through`.

Kilitlenen davranış:
* Varsayılan **kapalı** — ayar dosyasında yoksa arayüz "kapalı" gösterir.
* Açılıp kapatılabilir ve durum kalıcı.
* Metin "yes" açık sayılmaz; yalnız gerçek `True` açıktır.
"""
import unittest
from unittest.mock import patch

from modules import nxapi


class MascotClickThroughSetting(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.store = {}
        self._load = patch.object(nxapi, 'load_settings', side_effect=lambda: dict(self.store))
        self._save = patch.object(nxapi, 'save_settings', side_effect=self._save_settings)
        self._load.start()
        self._save.start()

    def _save_settings(self, **changes):
        self.saved.update(changes)
        self.store.update({k: v for k, v in changes.items() if v is not None})

    def tearDown(self):
        self._save.stop()
        self._load.stop()

    def test_default_is_off(self):
        self.assertFalse(nxapi.ui_settings()['mascot_click_through'])

    def test_turn_on_and_off(self):
        out = nxapi.ui_set('mascot_click_through', True)
        self.assertTrue(out['mascot_click_through'])
        self.assertIs(self.saved['mascot_click_through'], True)
        out = nxapi.ui_set('mascot_click_through', False)
        self.assertFalse(out['mascot_click_through'])

    def test_only_real_true_is_on(self):
        self.store['mascot_click_through'] = 'yes'
        self.assertFalse(nxapi.ui_settings()['mascot_click_through'])
        self.store['mascot_click_through'] = True
        self.assertTrue(nxapi.ui_settings()['mascot_click_through'])


if __name__ == '__main__':
    unittest.main()
