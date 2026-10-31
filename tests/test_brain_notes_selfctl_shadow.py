"""PR7 Closeout: notes data requests must not be consumed as UI navigation."""
import unittest
from unittest.mock import Mock

from modules import selfctl


class NotesSelfctlBoundaryTests(unittest.TestCase):
    def test_notes_data_requests_are_not_ui_navigation(self):
        for text in ("notlarımı göster", "notları göster", "notlarımı bana göster"):
            emit = Mock()
            self.assertIsNone(selfctl.handle(text, emit), text)
            emit.assert_not_called()

    def test_explicit_notes_page_navigation_still_works(self):
        for text in ("notlar sayfasını aç", "notlar sekmesini göster", "not ekranını aç"):
            emit = Mock()
            self.assertEqual(selfctl.handle(text, emit), "Notlar sayfasını açıyorum.", text)
            emit.assert_called_once_with("nav", "tools|takvim")


if __name__ == "__main__":
    unittest.main()
