"""Sesli "şuna bas / şuraya yaz" komutunun beyne bağlanması (3. dilim)."""
import unittest
from unittest.mock import patch

from modules import fast_commands


class CommandRouting(unittest.TestCase):
    def test_click_phrase_maps_to_pc_click(self):
        intent, args = fast_commands.resolve("not defterinde kaydet düğmesine bas")
        self.assertEqual(intent, "pc_click")
        self.assertEqual(args["window"], "not defteri")
        self.assertEqual(args["target"], "kaydet")

    def test_typing_phrase_maps_to_pc_type(self):
        intent, args = fast_commands.resolve("chrome da adres alanına youtube yaz")
        self.assertEqual(intent, "pc_type")
        self.assertEqual((args["window"], args["target"], args["text"]),
                         ("chrome", "adres", "youtube"))

    def test_read_only_phrases_still_win(self):
        self.assertEqual(fast_commands.resolve("chrome'da ne var")[0], "screen_controls")

    def test_unknown_phrases_are_not_swallowed(self):
        self.assertIsNone(fast_commands.resolve("bugün toplantı vardı"))


class Dispatch(unittest.TestCase):
    """Beyin, pc_hands'in sözünü olduğu gibi iletir: onay isterse cevap odur."""

    def test_risky_click_forwards_confirmation(self):
        from modules import engine_intents, pc_hands
        fake = {"status": "needs_confirmation", "text": "Onaylıyor musun?"}
        with patch.object(pc_hands, "click", return_value=fake) as click:
            text = engine_intents.dispatch(None, "pc_click",
                                           {"window": "not defteri", "target": "sil"}, "", "")
        self.assertEqual(text, "Onaylıyor musun?")
        self.assertEqual(click.call_count, 1)

    def test_type_forwards_text_and_target(self):
        from modules import engine_intents, pc_hands
        fake = {"status": "done", "text": "yazdım"}
        with patch.object(pc_hands, "type_text", return_value=fake) as typing:
            text = engine_intents.dispatch(None, "pc_type",
                                           {"window": "chrome", "target": "adres", "text": "youtube"}, "", "")
        self.assertEqual(text, "yazdım")
        self.assertEqual(typing.call_args[0][:3], ("chrome", "adres", "youtube"))


if __name__ == "__main__":
    unittest.main()
