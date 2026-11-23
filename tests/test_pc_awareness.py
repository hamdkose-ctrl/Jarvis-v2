"""Ekranda ne olduğunu modele sormadan söyler (yalnız okuma).

Canlı gereksinim: "ekranda ne var / hangi program açık" sorusu modelden
geliyordu; model ekranı görmediği için tahmin ediyordu. Bilgi Windows'tan kesin
okunur. Bu modül hiçbir şeye dokunmaz: tıklama, yazma, pencere değiştirme yok.
"""
import unittest
from unittest.mock import patch

from modules import fast_commands, pc_awareness


def _state():
    return {
        "platform": "nt",
        "screen": {"width": 1920, "height": 1080},
        "foreground": {"hwnd": 10, "title": "Toplantı notları - Not Defteri", "app": "notepad"},
        "windows": [
            {"hwnd": 10, "title": "Toplantı notları - Not Defteri", "app": "notepad"},
            {"hwnd": 11, "title": "Chrome", "app": "chrome"},
            {"hwnd": 12, "title": "Başka sekme - Chrome", "app": "chrome"},
        ],
    }


class Summary(unittest.TestCase):
    def test_foreground_is_named_first(self):
        text = pc_awareness.summary(_state())
        self.assertIn("Önde notepad", text)
        self.assertIn("Toplantı notları", text)
        self.assertTrue(text.index("Önde") < text.index("Açık programlar"))

    def test_repeated_app_is_counted_not_repeated(self):
        text = pc_awareness.summary(_state())
        self.assertIn("chrome (2 pencere)", text)

    def test_screen_size_is_included(self):
        self.assertIn("1920×1080", pc_awareness.summary(_state()))

    def test_empty_state_says_it_honestly(self):
        text = pc_awareness.summary({"windows": [], "foreground": None})
        self.assertIn("okuyamadım", text)

    def test_long_title_is_shortened(self):
        state = _state()
        state["foreground"] = {"hwnd": 10, "title": "A" * 200, "app": "word"}
        text = pc_awareness.summary(state)
        self.assertIn("…", text)
        self.assertLess(len(text), 300)

    def test_too_many_apps_are_trimmed(self):
        state = _state()
        state["windows"] = [{"hwnd": i, "title": "t", "app": f"app{i}"} for i in range(14)]
        text = pc_awareness.summary(state)
        self.assertIn("daha", text)

    def test_titles_put_foreground_first(self):
        self.assertEqual(pc_awareness.titles(_state())[0], "Toplantı notları - Not Defteri")


class Snapshot(unittest.TestCase):
    def test_foreground_is_matched_from_window_list(self):
        rows = [(10, "Not Defteri", "notepad"), (11, "Chrome", "chrome")]
        with patch("modules.system_control._app_windows", return_value=rows), \
             patch.object(pc_awareness, "_foreground_handle", return_value=11):
            state = pc_awareness.snapshot()
        self.assertEqual(state["foreground"]["app"], "chrome")
        self.assertEqual(len(state["windows"]), 2)

    def test_unknown_foreground_is_none_not_error(self):
        rows = [(10, "Not Defteri", "notepad")]
        with patch("modules.system_control._app_windows", return_value=rows), \
             patch.object(pc_awareness, "_foreground_handle", return_value=None):
            state = pc_awareness.snapshot()
        self.assertIsNone(state["foreground"])
        self.assertEqual(len(state["windows"]), 1)

    def test_reader_failure_does_not_raise(self):
        with patch("modules.system_control._app_windows", side_effect=OSError("boom")):
            state = pc_awareness.snapshot()
        self.assertEqual(state["windows"], [])
        self.assertIn("okuyamadım", pc_awareness.summary(state))


class Wiring(unittest.TestCase):
    def test_questions_take_the_fast_path(self):
        for text in ("ekranda ne var", "hangi program açık", "ne üstünde çalışıyorum",
                     "aktif pencere ne", "açık pencereler"):
            match = fast_commands.resolve(text)
            self.assertIsNotNone(match, text)
            self.assertEqual(match[0], "screen_summary", text)

    def test_unrelated_requests_are_not_hijacked(self):
        for text in ("ekranda ne var yaz", "hava nasıl", "hangi programı kurdun"):
            match = fast_commands.resolve(text)
            self.assertNotEqual(match[0] if match else None, "screen_summary", text)

    def test_intent_is_dispatched_without_a_model(self):
        from pathlib import Path
        import modules
        source = Path(modules.__file__).with_name("engine_intents.py").read_text(encoding="utf-8")
        self.assertIn('case "screen_summary"', source)
        key = 'case "screen_summary"'
        start = source.index(key) + len(key)
        rest = source[start:]
        block = rest[:rest.index('case "')]
        self.assertIn("pc_awareness.summary()", block)
        self.assertNotIn("llm", block)


if __name__ == "__main__":
    unittest.main()


class WindowTargeting(unittest.TestCase):
    """2. dilim: pencereyi bul ve içini oku — tahmin yok, dokunma yok."""

    def _windows(self):
        return [
            {"hwnd": 1, "title": "Not Defteri - belge.txt", "app": "notepad"},
            {"hwnd": 2, "title": "YouTube - Google Chrome", "app": "chrome"},
            {"hwnd": 3, "title": "Gmail - Google Chrome", "app": "chrome"},
        ]

    def test_unique_match_is_used(self):
        found = pc_awareness.find_window("not defteri", self._windows())
        self.assertEqual(found["reason"], "unique")
        self.assertEqual(found["match"]["hwnd"], 1)

    def test_ambiguous_never_guesses(self):
        found = pc_awareness.find_window("chrome", self._windows())
        self.assertEqual(found["reason"], "ambiguous")
        self.assertIsNone(found["match"])
        self.assertEqual(len(found["candidates"]), 2)

    def test_missing_window_is_reported(self):
        self.assertEqual(pc_awareness.find_window("excel", self._windows())["reason"], "missing")

    def test_no_name_uses_foreground(self):
        with patch.object(pc_awareness, "snapshot", return_value={
                "foreground": {"hwnd": 2, "title": "YouTube", "app": "chrome"},
                "windows": self._windows()}):
            found = pc_awareness.find_window("")
        self.assertEqual(found["reason"], "foreground")
        self.assertEqual(found["match"]["hwnd"], 2)

    def test_possessive_suffix_still_matches(self):
        self.assertEqual(pc_awareness.find_window("not defterinin", self._windows())["reason"],
                         "unique")

    def test_ambiguous_answer_asks_one_question(self):
        with patch.object(pc_awareness, "find_window", return_value={
                "reason": "ambiguous", "match": None, "query": "chrome",
                "candidates": self._windows()[1:]}):
            reply = pc_awareness.describe_window("chrome")
        self.assertEqual(reply["reason"], "ambiguous")
        self.assertIn("Hangisini", reply["text"])

    def test_missing_window_answer_is_honest(self):
        with patch.object(pc_awareness, "find_window", return_value={
                "reason": "missing", "match": None, "query": "excel", "candidates": []}):
            self.assertIn("göremiyorum", pc_awareness.describe_window("excel")["text"])

    def test_password_field_is_never_read(self):
        rows = [{"name": "Kullanıcı adı", "type": "ControlType.Edit"},
                {"name": "Şifre", "type": "ControlType.Edit"}]
        with patch.object(pc_awareness, "find_window", return_value={
                "reason": "unique", "match": self._windows()[0], "query": "not defteri",
                "candidates": []}), \
             patch("modules.desktop_uia.DesktopUI") as ui:
            ui.return_value.observe.return_value = {
                "title": "Not Defteri", "app": "notepad", "controls": rows}
            reply = pc_awareness.describe_window("not defteri")
        self.assertIn("içeriğini okumuyorum", reply["text"])
        self.assertNotIn("gizli123", reply["text"])

    def test_permission_error_is_explained(self):
        with patch.object(pc_awareness, "find_window", return_value={
                "reason": "unique", "match": self._windows()[0], "query": "not defteri",
                "candidates": []}), \
             patch("modules.desktop_uia.DesktopUI") as ui:
            ui.return_value.observe.side_effect = PermissionError("denied")
            reply = pc_awareness.describe_window("not defteri")
        self.assertIn("okuyamadım", reply["text"])

    def test_control_list_is_capped(self):
        rows = [{"name": f"düğme {i}", "type": "ControlType.Button"} for i in range(80)]
        with patch("modules.desktop_uia.DesktopUI") as ui:
            ui.return_value.observe.return_value = {"title": "T", "app": "x", "controls": rows}
            result = pc_awareness.controls({"title": "T", "hwnd": 1})
        self.assertLessEqual(len(result["controls"]), pc_awareness.MAX_CONTROLS)

    def test_kind_names_are_turkish(self):
        self.assertEqual(pc_awareness._kind_label("ControlType.Button"), "düğme")
        self.assertEqual(pc_awareness._kind_label("ControlType.Edit"), "metin alanı")

    def test_intent_is_wired(self):
        from pathlib import Path
        import modules
        source = Path(modules.__file__).with_name("engine_intents.py").read_text(encoding="utf-8")
        self.assertIn('case "screen_controls"', source)
        match = fast_commands.resolve("not defteri'nde ne var")
        self.assertEqual(match[0], "screen_controls")
        self.assertEqual(match[1]["window"], "not defteri")
