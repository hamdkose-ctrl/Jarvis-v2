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
        """Run the production notice branch's own idle decision for one lane state."""
        import ast
        from types import SimpleNamespace
        from unittest.mock import Mock
        tree = engine_source.tree()
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        block = next(n for n in ast.walk(main) if isinstance(n, ast.Try) and any(
            isinstance(node, ast.If) and 'lane is None' in ast.unparse(node.test)
            for node in n.finalbody))
        pause = SimpleNamespace(clear=Mock())
        emit = Mock()
        ns = {'time': SimpleNamespace(sleep=Mock()), 'pause_listening': pause,
              'voice_session': SimpleNamespace(voice_lane=lane), 'emit': emit}
        exec(compile(ast.fix_missing_locations(
            ast.Module(body=list(block.finalbody), type_ignores=[])),
            'real-notice-idle-tail', 'exec'), ns)
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


if __name__ == "__main__":
    unittest.main()
