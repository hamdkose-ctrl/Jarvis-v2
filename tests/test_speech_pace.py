import engine_source
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class SpeechPace(unittest.TestCase):
    def test_prompt_and_web_use_calm_pace(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "modules", "live.py"), encoding="utf-8").read()
        self.assertIn("Konuşma HIZIN: sakin", src)
        self.assertIn("slow: bool = False", src)
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


if __name__ == "__main__":
    unittest.main()
