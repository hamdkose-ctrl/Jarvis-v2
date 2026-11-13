import engine_source
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class SpeechPace(unittest.TestCase):
    def test_slow_lane_reduces_the_owner_rate(self):
        # "Cevap hızı" (live_silence_ms) Live'a aitti ve emekli oldu. Sakin anlatım yetkisi artık
        # tek ses sahibinin gerçek hız indirimindedir: speak(slow=True) çalma hızını düşürür.
        from types import SimpleNamespace
        from unittest.mock import Mock
        from modules import engine_voice

        submitted = []
        session = engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
        session.speak_enabled = True
        session.voice_lane = SimpleNamespace(
            say=lambda slug, voice, text, **kw: submitted.append(dict(text=text, **kw))
            or Mock(is_set=lambda: True))
        session.runtime = SimpleNamespace(
            flags={'speak': True}, emit=Mock(), log=Mock(), _cur_rid='tur1',
            profile=SimpleNamespace(slug='hamdi', data={'prefs': {'voice': 'tr_erkek', 'rate': 20}}))

        session.speak('Sakin anlatım', slow=True)
        session.speak('Normal anlatım')

        self.assertEqual([item['rate'] for item in submitted], [-15, 20])
        self.assertEqual([item['turn_id'] for item in submitted], ['tur1', 'tur1'])

    def test_calm_study_narration_uses_the_slow_lane(self):
        from web_study import WebStudy
        from types import SimpleNamespace
        from unittest.mock import Mock
        events=Mock()
        bridge=WebStudy(SimpleNamespace(events=events))
        self.assertTrue(bridge.study_speak('Sakin anlatım'))
        events.put.assert_called_once_with(('say_slow','Sakin anlatım'))
        main = engine_source.source()
        self.assertIn('kind in ("say", "say_slow")', main)

    def test_dock_has_stop_button(self):
        js = open(os.path.join(os.path.dirname(__file__), "..", "webui", "nx.js"), encoding="utf-8").read()
        self.assertIn('data-act="dstop"', js)
        self.assertIn("ACT.dstop=", js)

    def notice_tail(self, lane):
        """Exercise the shared PRODUCTION idle emitter used by the real engine.

        The old test extracted a Try.finalbody by looking for the literal
        expression 'lane is None'. The safety fix correctly delegates to the
        common speaker gate, so that syntax-shape probe was obsolete.
        """
        from types import SimpleNamespace
        from unittest.mock import Mock
        from modules import engine_loop
        emit = Mock()
        engine_loop._emit_idle_if_silent(
            SimpleNamespace(emit=emit),
            SimpleNamespace(voice_lane=lane),
        )
        return emit

    def idle_emit_for(self, busy, unconfirmed):
        from types import SimpleNamespace
        lane = SimpleNamespace(is_busy=lambda: busy, stop_unconfirmed=lambda: unconfirmed)
        emit = self.notice_tail(lane)
        return [call.args for call in emit.call_args_list]

    def test_notice_tail_only_claims_idle_after_a_device_confirmed_silence(self):
        # §P1 at the orb: a cut the device never confirmed may still be audible,
        # so the loop's own "idle" must not go out over live speech. Speech that
        # really ended (or never existed) still releases the orb.
        self.assertEqual(self.idle_emit_for(False, False), [('state', 'idle')])
        self.assertEqual(self.idle_emit_for(False, True), [])
        self.assertEqual(self.idle_emit_for(True, False), [])

    def test_notice_tail_without_a_speech_owner_still_goes_idle(self):
        emit = self.notice_tail(None)
        self.assertEqual([call.args for call in emit.call_args_list], [('state', 'idle')])


class SpokenLengthBound(unittest.TestCase):
    """What a long answer reaches the speaker as: measured, not hoped for.

    `_short_for_speech` is the engine's own cut before speech (engine_loop:458) and
    the phone's written view (phone.py:928). It has always preferred a sentence end;
    when it found none the fallback was a raw character cut, so the last thing the
    user heard was half a word ("…birka"). Nothing here rewrites the answer.
    """

    def short(self, text, limit=400):
        from unittest.mock import Mock
        from modules.engine_output import _short_for_speech
        return _short_for_speech(Mock(), text, limit)

    def test_a_short_answer_is_spoken_whatever_its_shape(self):
        for text in ("Merhaba.", "a" * 400, "Tam cümle, kesinti yok."):
            with self.subTest(text=text[:12]):
                self.assertEqual(self.short(text), text)

    def test_a_complete_sentence_is_cut_at_its_end(self):
        spoken = self.short("abc def. " * 120)
        self.assertTrue(spoken.endswith("abc def."), repr(spoken[-12:]))
        self.assertLess(len(spoken), 400)

    def test_an_answer_without_a_sentence_end_never_stops_mid_word(self):
        # The defect measured on 13 Kasım 2026: 400 characters of words with no "."
        # at all used to be read as "…kelime" cut into "…keli".
        spoken = self.short("kelime " * 200)
        self.assertTrue(spoken.endswith("kelime"), repr(spoken[-12:]))
        self.assertLess(len(spoken), 400)

    def test_the_cut_only_shortens_and_never_rewrites(self):
        for text in ("abc def. " * 120, "kelime " * 200, "x" * 900):
            spoken = self.short(text)
            with self.subTest(text=text[:10]):
                self.assertTrue(text.startswith(spoken))
                self.assertLessEqual(len(spoken), 400)

    def test_a_single_unbroken_token_is_still_bounded(self):
        # A URL or a base64 blob has no space either; it must not be read forever,
        # so this one case keeps the character bound and says so rather than lying.
        self.assertEqual(self.short("x" * 900), "x" * 400)


if __name__ == "__main__":
    unittest.main()
