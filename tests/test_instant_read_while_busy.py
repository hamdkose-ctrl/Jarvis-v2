"""Meşgulken anlık salt-okuma yanıtı: varsayılan kapalı, açılınca model yok."""
import threading
import unittest
from unittest.mock import patch

from modules import engine_queue, engine_intents


class _Log:
    def info(self, *a, **k):
        pass


class _Profil:
    slug = 'hamdi'
    name = 'Hamdi'


class _Ses:
    def __init__(self):
        self.okunan = []

    def speak(self, text, **k):
        self.okunan.append(text)


class _Runtime:
    def __init__(self, mesgul=False):
        self._execution_lock = threading.Lock()
        self._mesgul_tut = None
        if mesgul:
            self._mesgul_tut = self._execution_lock.acquire(blocking=False)
        self.log = _Log()
        self.voice = _Ses()
        self.olaylar = []
        self.hatalar = []
        self.pause_listening = threading.Event()

    def pc_profile(self):
        return _Profil()

    def _get_profile(self, name):
        return _Profil()

    def _emit_for(self, profile, kind, text, source='', rid=None):
        self.olaylar.append((kind, text))
        return True

    def _tr_lower(self, text):
        return text.casefold()

    def _record_failure(self, kaynak):
        self.hatalar.append(kaynak)


def _ayar(deger):
    return patch('config.load_settings', lambda: {'instant_read_while_busy': deger})


class InstantReadWhileBusyTests(unittest.TestCase):
    def setUp(self):
        self._gercek = engine_intents.dispatch
        engine_intents.dispatch = lambda rt, i, a, c, l: 'Saat 04:05'

    def tearDown(self):
        engine_intents.dispatch = self._gercek

    def test_default_off_keeps_the_old_queue_behaviour(self):
        rt = _Runtime(mesgul=True)
        with _ayar(False):
            self.assertFalse(engine_queue._answer_instant_while_busy(rt, 'saat kaç', 'hamdi', 'Hamdi', 'ses', 'r1'))
        self.assertEqual(rt.olaylar, [])
        self.assertEqual(rt.voice.okunan, [])

    def test_idle_runtime_is_not_intercepted(self):
        rt = _Runtime(mesgul=False)
        with _ayar(True):
            self.assertFalse(engine_queue._answer_instant_while_busy(rt, 'saat kaç', 'hamdi', 'Hamdi', 'ses', 'r2'))
        self.assertEqual(rt.olaylar, [])

    def test_busy_runtime_answers_read_only_command_and_speaks(self):
        rt = _Runtime(mesgul=True)
        with _ayar(True):
            okundu = engine_queue._answer_instant_while_busy(rt, 'saat kaç', 'hamdi', 'Hamdi', 'ses', 'r3')
        self.assertTrue(okundu)
        self.assertEqual(rt.olaylar, [('user', 'saat kaç'), ('assistant', 'Saat 04:05')])
        self.assertEqual(rt.voice.okunan, ['Saat 04:05'])

    def test_busy_runtime_answers_local_arithmetic(self):
        rt = _Runtime(mesgul=True)
        with _ayar(True):
            self.assertTrue(engine_queue._answer_instant_while_busy(rt, '25 çarpı 4', 'hamdi', 'Hamdi', 'ses', 'r4'))
        self.assertEqual(rt.voice.okunan, ['Sonuc 100.'])

    def test_busy_runtime_never_answers_effect_commands(self):
        for metin in ('sesi kıs', 'steam aç', 'ekran görüntüsü al', 'hava nasıl'):
            rt = _Runtime(mesgul=True)
            with _ayar(True):
                self.assertFalse(engine_queue._answer_instant_while_busy(rt, metin, 'hamdi', 'Hamdi', 'ses', 'r5'), metin)
            self.assertEqual(rt.olaylar, [], metin)

    def test_other_owner_is_never_answered(self):
        rt = _Runtime(mesgul=True)
        with _ayar(True):
            self.assertFalse(engine_queue._answer_instant_while_busy(rt, 'saat kaç', 'baska', 'Baska', 'telefon', 'r6'))
        self.assertEqual(rt.olaylar, [])


if __name__ == '__main__':
    unittest.main()
