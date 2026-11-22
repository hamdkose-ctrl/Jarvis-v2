"""Büyük harf Türkçe komutlar: tek katlama tanımı, kelime oyunu yok.

Canlı hata (22 Kasım 2026): "HEDEF İPTAL" iptal etmedi, "İPTAL" adında yeni iş
açtı. Sebep str.casefold()'un 'İ' harfini 'i' + birleşik nokta yapması. Aynı
sınıf hata onay, uygulama seçimi ve süre ifadelerinde de vardı.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import brain_core_map, command_execution, confirmation, goal_executor, text_fold


class FoldTests(unittest.TestCase):
    def test_fold_matches_lowercase_for_turkish_uppercase(self):
        self.assertEqual(text_fold.fold("HEDEF İPTAL"), "hedef iptal")
        self.assertEqual(text_fold.fold("İSTANBUL"), "istanbul")
        self.assertEqual(text_fold.fold("IŞIK"), "ışık")
        self.assertEqual(text_fold.fold_command("  EVET.  "), "evet")
        # Kök neden: standart casefold bu eşitliği sağlamıyor.
        self.assertNotEqual("İPTAL".casefold(), "iptal")

    def test_command_paths_use_the_single_definition(self):
        """Komut eşleştiren modüller tek katlamayı kullanır (sessiz geri dönüş olmasın)."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "modules"
        for name in ("goal_executor.py", "confirmation.py", "app_actions.py",
                     "command_execution.py", "brain_core_map.py", "engine_tools.py"):
            source = (root / name).read_text(encoding="utf-8")
            self.assertIn("text_fold", source, name)

    def test_one_definition_is_shared(self):
        runtime = SimpleNamespace()
        from modules import engine_tools
        self.assertEqual(engine_tools._tr_lower(runtime, "SESİ KAPAT"), "sesi kapat")
        self.assertEqual(goal_executor._low("HEDEF İPTAL"), "hedef iptal")


class ConfirmationTests(unittest.TestCase):
    def test_uppercase_yes_and_no_are_understood(self):
        self.assertIs(confirmation.decision("EVET"), True)
        self.assertIs(confirmation.decision("ONAYLIYORUM"), True)
        self.assertIs(confirmation.decision("HAYIR"), False)
        self.assertIs(confirmation.decision("VAZGEÇ"), False)

    def test_uppercase_choice_title_is_matched(self):
        self.assertEqual(confirmation.choice_index("İSTANBUL", ["Ankara", "İstanbul"]), 1)
        self.assertEqual(confirmation.choice_index("İSTAN", ["Ankara", "İstanbul"]), 1)


class PendingAppTests(unittest.TestCase):
    def test_uppercase_app_name_resumes_the_choice(self):
        session = SimpleNamespace(pending_app={"at": 0, "choices": ["Kamera", "Notlar"]})
        runtime = SimpleNamespace(_session=lambda: session)
        del session.pending_app["at"]
        session.pending_app["at"] = command_execution.time.monotonic()
        with patch.object(command_execution, "open_app", return_value="Kamera açıldı.") as opened, \
             patch("modules.brain_entry.matched_protocol", return_value=False):
            self.assertEqual(command_execution.continue_app(runtime, "KAMERA"), "Kamera açıldı.")
        opened.assert_called_once()


class DelayTests(unittest.TestCase):
    def test_uppercase_duration_is_understood(self):
        def args(duration):
            return {"operation": "snooze", "title": "toplantı", "duration": duration}
        self.assertEqual(
            brain_core_map._reminder_protocol_args(args("10 DAKİKA"))["minutes"], 10)
        self.assertEqual(
            brain_core_map._reminder_protocol_args(args("YARIM SAAT"))["minutes"], 30)
        self.assertEqual(
            brain_core_map._reminder_protocol_args(args("BİR GÜN"))["minutes"], 1440)

    def test_lowercase_still_works_the_same(self):
        args = {"operation": "snooze", "title": "toplantı", "duration": "10 dakika"}
        self.assertEqual(brain_core_map._reminder_protocol_args(args)["minutes"], 10)


if __name__ == "__main__":
    unittest.main()
