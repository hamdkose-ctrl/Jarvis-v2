from __future__ import annotations

import unittest
from unittest.mock import patch

from modules import command_manager, phone


class TelefonHttpsTestleri(unittest.TestCase):
    """Tailscale HTTPS yalnız açık izinle kurulur; sessiz kurulum yok."""

    def test_izinsiz_kurulum_reddedilir(self):
        with self.assertRaises(ValueError):
            phone.https_setup(8765, consent=False)

    def test_gecersiz_port_reddedilir(self):
        for port in (0, 80, 70000, '8765', True):
            with self.assertRaises(ValueError):
                phone.https_setup(port, consent=True)

    def test_basarili_kurulum_url_dondurur(self):
        with patch.object(phone, 'https_set', return_value=(True, 'ok')), \
             patch.object(phone, 'https_url', return_value='https://pc.tail.ts.net'):
            kayit = phone.https_setup(8765, consent=True)
        self.assertTrue(kayit['ok'])
        self.assertEqual(kayit['url'], 'https://pc.tail.ts.net')

    def test_basarisiz_kurulum_gerekce_dondurur(self):
        with patch.object(phone, 'https_set',
                          return_value=(False, 'Tailscale hesabında HTTPS etkin değil')):
            kayit = phone.https_setup(8765, consent=True)
        self.assertFalse(kayit['ok'])
        self.assertIn('HTTPS', kayit['detail'])

    def test_komut_kurulumu_cagirir(self):
        with patch.object(phone, 'https_setup',
                          return_value={'ok': True, 'on': True, 'url': 'https://pc.tail.ts.net',
                                        'detail': ''}) as kur:
            yanit = command_manager.engine_control(
                'telefon https kur', source='masaustu', sleeping=False,
                close=lambda: 'kapandı', set_sleep=lambda *_: 'uyku')
        self.assertTrue(kur.call_args.kwargs['consent'])
        self.assertTrue(kur.call_args.kwargs['on'])
        self.assertIn('pc.tail.ts.net', yanit)


if __name__ == '__main__':
    unittest.main()
