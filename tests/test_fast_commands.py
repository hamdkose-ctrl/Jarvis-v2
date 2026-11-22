"""Hızlı yol: model gerektirmeyen komutlar tam eşleşmeyle yakalanır."""
import unittest

from modules.fast_commands import KNOWN_APPS, MAX_CHARS, normalize, resolve


class FastPathMatchTests(unittest.TestCase):
    def test_time_and_date_are_resolved_without_a_model(self):
        for metin in ("saat kaç", "Saat kaç?", "saat", "saat kaç oldu"):
            self.assertEqual(resolve(metin), ("fast_time", {}), metin)
        for metin in ("tarih ne", "bugün günlerden ne", "bugün ayın kaçı"):
            self.assertEqual(resolve(metin), ("fast_date", {}), metin)

    def test_speech_and_level_commands_reach_their_single_owner(self):
        self.assertEqual(resolve("sus"), ("fast_speech_stop", {}))
        self.assertEqual(resolve("sesi kapat"), ("audio_action", {"action": "mute"}))
        self.assertEqual(resolve("sesi aç"), ("audio_action", {"action": "unmute"}))
        self.assertEqual(resolve("sesi arttır"), ("audio_action", {"action": "volume_up"}))
        self.assertEqual(resolve("sesi kıs"), ("audio_action", {"action": "lower"}))
        self.assertEqual(resolve("sesi yüzde 40 yap"),
                         ("level_set", {"property": "volume", "level": 40}))
        self.assertEqual(resolve("parlaklığı yüzde 70 yap"),
                         ("level_set", {"property": "brightness", "level": 70}))

    def test_level_is_clamped_to_the_device_range(self):
        self.assertEqual(resolve("sesi yüzde 150 yap")[1]["level"], 100)

    def test_media_commands(self):
        self.assertEqual(resolve("sonraki şarkı"), ("media_action", {"action": "next"}))
        self.assertEqual(resolve("önceki şarkı"), ("media_action", {"action": "prev"}))
        self.assertEqual(resolve("müziği duraklat"), ("media_action", {"action": "play_pause"}))

    def test_only_known_applications_take_the_fast_path(self):
        self.assertIn("steam", KNOWN_APPS)
        self.assertEqual(resolve("steam aç"), ("app_open", {"name": "steam"}))
        self.assertEqual(resolve("chrome uygulamasını aç"), ("app_open", {"name": "chrome"}))
        self.assertIsNone(resolve("kapıyı aç"))
        self.assertIsNone(resolve("bilinmeyenprogram aç"))

    def test_ambiguous_or_conversational_commands_fall_through_to_brain(self):
        # "hava nasıl" artık hızlı yolda (salt okuma); serbest sorular modelde kalır.
        for metin in ("hava nasıl olacak yarın", "bunu neden yaptın", "saat kaçta toplantı var",
                      "ses", "yarın hava nasıl olacak", ""):
            self.assertIsNone(resolve(metin), metin)

    def test_long_text_never_takes_the_fast_path(self):
        self.assertIsNone(resolve("a" * (MAX_CHARS + 1)))

    def test_turkish_letters_and_punctuation_are_normalized(self):
        self.assertEqual(normalize("Sesi KIS!"), "sesi kis")
        self.assertEqual(normalize("  Saat   kaç?  "), "saat kac")
        self.assertEqual(normalize("İSTANBUL"), "istanbul")


if __name__ == "__main__":
    unittest.main()


class _SahteLog:
    def __init__(self):
        self.satirlar = []

    def info(self, *a, **k):
        self.satirlar.append(a)


class _SahteRuntime:
    """Yalnız hızlı yolun dokunduğu yüzey: saat, log, hata kaydı."""

    def __init__(self):
        import time as _time
        self.time = _time
        self.log = _SahteLog()
        self.hatalar = []

    def _record_failure(self, kaynak):
        self.hatalar.append(kaynak)


class FastPathTurnTests(unittest.TestCase):
    def test_answer_is_plain_text_never_a_tuple(self):
        """Canlı hata 11:39: ekrana \"('...', None, None)\" sızdı; dönüş düz metin olmalı."""
        from modules.engine_loop import _fast_command_turn
        from modules import engine_intents
        eski = engine_intents.dispatch
        engine_intents.dispatch = lambda *a: "Chrome penceresi açık; açılışı doğruladım."
        try:
            out = _fast_command_turn(_SahteRuntime(), "chrome aç")
        finally:
            engine_intents.dispatch = eski
        self.assertIsInstance(out, str)
        self.assertNotIn("None", out)

    def setUp(self):
        from modules import engine_intents
        self.engine_intents = engine_intents
        self._gercek = engine_intents.dispatch

    def tearDown(self):
        self.engine_intents.dispatch = self._gercek

    def test_match_returns_answer_without_touching_the_model(self):
        from modules.engine_loop import _fast_command_turn
        cagrilar = []
        self.engine_intents.dispatch = lambda rt, intent, a, cmd, low: (cagrilar.append((intent, dict(a), cmd)),
                                                                       "Saat 03:14")[1]
        out = _fast_command_turn(_SahteRuntime(), "saat kaç")
        self.assertEqual(out, "Saat 03:14")
        self.assertEqual(cagrilar, [("fast_time", {}, "saat kaç")])

    def test_unmatched_command_returns_none_so_brain_still_runs(self):
        from modules.engine_loop import _fast_command_turn
        self.engine_intents.dispatch = lambda *a: self.fail("eşleşmeyen komut dispatch edilmemeli")
        self.assertIsNone(_fast_command_turn(_SahteRuntime(), "bunu neden yaptın"))

    def test_dispatch_failure_falls_back_instead_of_swallowing_the_turn(self):
        from modules.engine_loop import _fast_command_turn
        rt = _SahteRuntime()

        def patlat(*a):
            raise RuntimeError("bozuk")

        self.engine_intents.dispatch = patlat
        self.assertIsNone(_fast_command_turn(rt, "sesi kıs"))
        self.assertEqual(rt.hatalar, ["modules/engine_loop.py:fast_command"])


class FastPathExtraTests(unittest.TestCase):
    def test_close_requests_confirmation_only_for_known_apps(self):
        self.assertEqual(resolve("steam kapat"), ("app_close", {"name": "steam"}))
        self.assertEqual(resolve("spotify uygulamasını kapat"),
                         ("app_close", {"name": "spotify"}))
        self.assertIsNone(resolve("kapıyı kapat"))

    def test_screenshot_is_plain_read_command(self):
        self.assertEqual(resolve("ekran görüntüsü al"), ("screen_capture", {}))

    def test_arithmetic_is_answered_locally(self):
        from modules.fast_commands import compute
        self.assertEqual(compute("25 çarpı 4"), "Sonuc 100.")
        self.assertEqual(compute("12 artı 8"), "Sonuc 20.")
        self.assertEqual(compute("100 bölü 4"), "Sonuc 25.")
        self.assertEqual(compute("3 üssü 4"), "Sonuc 81.")
        self.assertEqual(compute("250 * 4 - 100"), "Sonuc 900.")

    def test_arithmetic_refuses_unsafe_or_ambiguous_input(self):
        from modules.fast_commands import compute
        for metin in ('__import__("os")', '0/0', '1+', '5 + 3 = 8',
                      'bunu neden yaptın', 'saat kaç', 'sesi kıs'):
            self.assertIsNone(compute(metin), metin)

    def test_calc_reaches_the_turn_before_the_model(self):
        from modules.engine_loop import _fast_command_turn
        from modules import engine_intents
        eski = engine_intents.dispatch
        engine_intents.dispatch = lambda *a: self.fail("hesap komutu dispatch edilmemeli")
        try:
            self.assertEqual(_fast_command_turn(_SahteRuntime(), "25 çarpı 4"),
                             "Sonuc 100.")
        finally:
            engine_intents.dispatch = eski


class FastPathReadTests(unittest.TestCase):
    """Salt-okuma komutları: model çağrısı yok, etki yok."""

    def test_weather_without_location_uses_saved_city(self):
        for metin in ('hava nasıl', 'hava durumu', 'bugün hava nasıl'):
            self.assertEqual(resolve(metin), ('weather', {}), metin)

    def test_agenda_day_plan(self):
        self.assertEqual(resolve('bugün ne var'),
                         ('agenda_read', {'view': 'day_plan', 'period': 'today'}))
        self.assertEqual(resolve('yarın neler var'),
                         ('agenda_read', {'view': 'day_plan', 'period': 'tomorrow'}))

    def test_note_count(self):
        self.assertEqual(resolve('kaç notum var'), ('notes_read', {'which': 'count'}))

    def test_open_ended_questions_still_go_to_the_model(self):
        for metin in ('hava nasıl olacak yarın', 'bugün ne yapmalıyım'):
            self.assertIsNone(resolve(metin), metin)
