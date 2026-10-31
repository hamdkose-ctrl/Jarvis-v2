"""PR7 Closeout: canonical notes data requests must beat legacy UI navigation."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from modules import brain_precedence


class _Runtime:
    def __init__(self):
        self.emit = Mock()
        self.system_control = SimpleNamespace(windows_settings=Mock(return_value=None))
        self._file_command = Mock(return_value=None)
        self._user_command = Mock(return_value=None)
        self._planner_command = Mock(return_value=None)
        self._macro_teach = Mock(return_value=None)
        self._macro_manage = Mock(return_value=None)
        self._macro_run = Mock(return_value=None)
        self._extra_commands = Mock(return_value=None)

    @staticmethod
    def _tr_lower(text):
        return text.replace("I", "ı").replace("İ", "i").lower()


class NotesSelfctlBoundaryTests(unittest.TestCase):
    def test_canonical_notes_data_plan_is_not_consumed_as_ui_navigation(self):
        for text in ("notlarımı göster", "notları göster", "notlarımı bana göster"):
            runtime = _Runtime()
            claimed = brain_precedence.claim(runtime, text, ("notes_read", {"which": "all"}))
            self.assertIsNone(claimed, text)
            runtime.emit.assert_not_called()

    def test_explicit_notes_page_navigation_still_works_without_data_plan(self):
        for text in ("notlar sayfasını aç", "notlar sekmesini göster", "not ekranını aç"):
            runtime = _Runtime()
            claimed = brain_precedence.claim(runtime, text, None)
            self.assertEqual(claimed, ("selfctl", "Notlar sayfasını açıyorum."), text)
            runtime.emit.assert_called_once_with("nav", "tools|takvim")


if __name__ == "__main__":
    unittest.main()
