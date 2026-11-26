"""T1: WhatsApp aramada tam ad korunur, ek atması aday doğrulamasıyla yapılır.

Kural (kullanıcı, 26 Kasım): "'bitaneme' derken 'bitanem'e demek istiyorum" — ama
"Fatma" gibi adlar bozulmamalı. Sıra: tam ad → ek atılmış → son kelime.
"""
import unittest
from unittest import mock

from modules import whatsapp_ui


class Variants(unittest.TestCase):
    def test_real_names_are_kept_intact(self):
        self.assertEqual(whatsapp_ui.search_variants("Fatma")[0], "fatma")
        self.assertEqual(whatsapp_ui.search_variants("Merve")[0], "merve")

    def test_full_name_is_not_collapsed_to_one_word(self):
        self.assertEqual(whatsapp_ui.search_variants("Mehmet Ali Yılmaz")[0], "mehmet ali yilmaz")

    def test_suffix_fallback_is_ordered_after_the_full_name(self):
        self.assertEqual(whatsapp_ui.search_variants("bitaneme"), ["bitaneme", "bitanem"])
        self.assertEqual(whatsapp_ui.search_variants("bir taneme"), ["taneme", "tanem"])

    def test_apostrophe_cuts_the_suffix(self):
        self.assertEqual(whatsapp_ui.search_variants("Zeynep'e"), ["zeynep"])

    def test_two_letter_names_allowed(self):
        self.assertEqual(whatsapp_ui.search_variants("Ay"), ["ay"])

    def test_single_letter_is_refused(self):
        self.assertEqual(whatsapp_ui.search_variants("a"), [])
        self.assertEqual(whatsapp_ui.open_search("a")["status"], "empty")


class VerificationDrivesTheFallback(unittest.TestCase):
    """Ek atması körlemesine değil: "sonuç yok" görülünce bir sonraki adaya geçilir."""

    def _search(self, name, no_results_for):
        typed = []
        gui = mock.MagicMock()
        gui.hotkey = lambda *keys: None
        gui.press = lambda key: None
        with mock.patch.dict("sys.modules", {"pyautogui": gui}), \
             mock.patch.object(whatsapp_ui, "show", return_value={"status": "done", "text": ""}), \
             mock.patch.object(whatsapp_ui.time, "sleep", lambda *_: None), \
             mock.patch("modules.pc_hands.write_clipboard", lambda text: typed.append(text) or True), \
             mock.patch.object(whatsapp_ui, "_no_results_on_screen",
                               lambda: typed and typed[-1] == no_results_for):
            result = whatsapp_ui.open_search(name)
        return result, typed

    def test_bitaneme_falls_back_to_bitanem(self):
        result, typed = self._search("bitaneme", no_results_for="bitaneme")
        self.assertEqual(typed, ["bitaneme", "bitanem"])
        self.assertIn("bitanem", result["text"])

    def test_fatma_is_not_shortened(self):
        result, typed = self._search("Fatma", no_results_for="")
        self.assertEqual(typed, ["fatma"])
        self.assertIn("fatma", result["text"])


if __name__ == "__main__":
    unittest.main()
