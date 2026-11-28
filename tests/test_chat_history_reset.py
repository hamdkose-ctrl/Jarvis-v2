from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import command_manager, llm


class SohbetGecmisiTestleri(unittest.TestCase):
    """Kullanıcı konuşma hafızasını sıfırlayabilmeli."""

    def _context(self):
        return SimpleNamespace(profile=SimpleNamespace(slug='alice'),
                               session=SimpleNamespace(), emit=None)

    def test_komut_gecmisi_temizler(self):
        with patch.object(llm, 'reset_history') as sifirla:
            yanit = command_manager.dispatch(self._context(), 'sohbet geçmişini temizle',
                                             'sohbet geçmişini temizle')
        sifirla.assert_called_once_with('alice')
        self.assertIn('temizledim', yanit)

    def test_kipler_kabul_edilir(self):
        for komut in ('geçmişi temizle', 'sohbet geçmişi sıfırla', 'geçmişini sil'):
            with self.subTest(komut=komut), \
                 patch.object(llm, 'reset_history') as sifirla:
                command_manager.dispatch(self._context(), komut, komut)
            self.assertTrue(sifirla.called)


if __name__ == '__main__':
    unittest.main()
