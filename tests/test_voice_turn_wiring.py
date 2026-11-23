"""Sıra alma hattı: yarım kalan cümlede tek devam kaydı (anahtar kapalıyken eski davranış).

Kilitlenen davranış:
* `voice_turn_reopen` ayarı **yoksa/kapalıysa** `listen()` eskisi gibi tek kayıt
  yapar ve tek çeviri döndürür — davranış birebir aynı.
* Açıkken: yazı **tamam** ise devam kaydı alınmaz (boşuna mikrofon açılmaz).
* Açıkken: yazı yarım ise bir kez devam kaydı alınır ve iki parça birleştirilir.
* Devam kaydı boş/boş çeviri dönerse ilk yazı korunur (söz kaybolmaz).
* Devam kaydı en fazla bir kez denenir; sonsuz döngü yok.
* Mikrofon/çeviri hatası ilk yazıyı düşürmez.
"""
import unittest
from unittest.mock import patch

from modules import voice


class ReopenWiring(unittest.TestCase):
    def _run(self, *, setting, first, second=b'pcm-2', second_text='devam ettim.'):
        calls = {'capture': 0, 'recognize': []}
        texts = [first, second_text]

        def fake_capture(**_kw):
            calls['capture'] += 1
            return second if calls['capture'] > 1 else b'pcm-1'

        def fake_recognize(raw, *a, **kw):
            calls['recognize'].append(raw)
            if calls['capture'] > 1:
                return texts[1]
            return texts[0]

        with patch.object(voice, 'capture', side_effect=fake_capture), \
             patch.object(voice, 'recognize', side_effect=fake_recognize), \
             patch.object(voice.config, 'load_settings', return_value=({'voice_turn_reopen': True} if setting else {})):
            out = voice.listen(timeout=6)
        return out, calls

    def test_default_off_keeps_single_capture(self):
        out, calls = self._run(setting=False, first='elma ve')
        self.assertEqual(out, 'elma ve')
        self.assertEqual(calls['capture'], 1)
        self.assertEqual(len(calls['recognize']), 1)

    def test_open_joins_incomplete_sentence(self):
        out, calls = self._run(setting=True, first='yarın saat üçte')
        self.assertEqual(calls['capture'], 2)
        self.assertEqual(out, 'yarın saat üçte devam ettim.')

    def test_complete_sentence_never_reopens(self):
        out, calls = self._run(setting=True, first='Yarın gelirim.')
        self.assertEqual(calls['capture'], 1)
        self.assertEqual(out, 'Yarın gelirim.')

    def test_empty_continuation_keeps_first_text(self):
        out, calls = self._run(setting=True, first='elma ve', second=b'', second_text='')
        self.assertEqual(calls['capture'], 2)
        self.assertEqual(out, 'elma ve')

    def test_second_capture_is_bounded(self):
        """Devam kaydı kısa ve sınırlı olmalı; ana kayıt süresi değişmez."""
        seen = []

        def fake_capture(**kw):
            seen.append(kw)
            return b'pcm' if len(seen) == 1 else b'pcm2'

        with patch.object(voice, 'capture', side_effect=fake_capture), \
             patch.object(voice, 'recognize', side_effect=lambda raw, *a, **kw: 'elma ve' if len(seen) == 1 else 'armut'), \
             patch.object(voice.config, 'load_settings', return_value={'voice_turn_reopen': True}):
            voice.listen(timeout=6)
        self.assertEqual(seen[0]['timeout'], 6)
        self.assertLessEqual(seen[1]['timeout'], 3)

    def test_recognize_error_does_not_lose_first_text(self):
        def boom(raw, *a, **kw):
            if len(calls['recognize']) > 1:
                raise RuntimeError('çeviri hatası')
            return 'elma ve'

        calls = {'recognize': []}

        def fake_recognize(raw, *a, **kw):
            calls['recognize'].append(raw)
            return boom(raw)

        with patch.object(voice, 'capture', side_effect=lambda **kw: b'pcm'), \
             patch.object(voice, 'recognize', side_effect=fake_recognize), \
             patch.object(voice.config, 'load_settings', return_value={'voice_turn_reopen': True}):
            with self.assertRaises(RuntimeError):
                voice.listen(timeout=6)


class SettingRead(unittest.TestCase):
    def test_setting_error_falls_back_to_off(self):
        with patch.object(voice.config, 'load_settings', side_effect=OSError('okunamadı')):
            self.assertFalse(voice._turn_reopen_enabled())

    def test_setting_true_is_read(self):
        with patch.object(voice.config, 'load_settings', return_value={'voice_turn_reopen': True}):
            self.assertTrue(voice._turn_reopen_enabled())


if __name__ == '__main__':
    unittest.main()
