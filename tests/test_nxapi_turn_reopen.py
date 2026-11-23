"""Arayüz ayarı: `voice_turn_reopen` (yarım cümle devamı).

Kilitlenen davranış:
* Varsayılan **kapalı** — ayar dosyasında yoksa arayüz "kapalı" gösterir.
* Açılıp kapatılabilir ve durum kalıcı.
* Bilinmeyen anahtar hâlâ reddedilir (arayüzden her ayar değiştirilemez).
"""
import unittest
from unittest.mock import patch

from modules import nxapi


class TurnReopenSetting(unittest.TestCase):
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
        self.assertFalse(nxapi.ui_settings()['voice_turn_reopen'])

    def test_turn_on_and_off(self):
        out = nxapi.ui_set('voice_turn_reopen', True)
        self.assertTrue(out['voice_turn_reopen'])
        self.assertIs(self.saved['voice_turn_reopen'], True)
        out = nxapi.ui_set('voice_turn_reopen', False)
        self.assertFalse(out['voice_turn_reopen'])

    def test_value_is_coerced_to_bool(self):
        self.assertTrue(nxapi.ui_settings()['voice_turn_reopen'] is False)
        self.store['voice_turn_reopen'] = True
        self.assertTrue(nxapi.ui_settings()['voice_turn_reopen'])
        self.store['voice_turn_reopen'] = 'yes'          # metin değer açık sayılmaz
        self.assertFalse(nxapi.ui_settings()['voice_turn_reopen'])

    def test_unknown_key_still_rejected(self):
        with self.assertRaises(ValueError):
            nxapi.ui_set('dosya_sil', True)


if __name__ == '__main__':
    unittest.main()
