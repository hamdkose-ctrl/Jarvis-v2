"""Dört maddenin hatta bağlanması: bellek kapısı, Core şeması, uyanıklık, dünya olayları."""
import unittest
from unittest.mock import patch

from modules import core_policy, fast_commands, memory_gate, pc_hands


class MemoryWiring(unittest.TestCase):
    def test_history_summary_shrinks_long_input(self):
        items = [("user", "x" * 400) for _ in range(40)]
        out = memory_gate.summarise_history(items)
        self.assertLessEqual(len(out), memory_gate.SUMMARY_KEEP + 1)

    def test_short_history_is_untouched(self):
        items = [("user", "merhaba"), ("assistant", "selam")]
        self.assertEqual(memory_gate.summarise_history(items), items)


class CoreWiring(unittest.TestCase):
    def test_hands_risk_agrees_with_core_policy(self):
        self.assertTrue(pc_hands.is_risky("Sil"))
        self.assertTrue(pc_hands.is_risky("şifre alanı"))
        self.assertFalse(pc_hands.is_risky("kaydet"))

    def test_policy_covers_password_even_without_risk_word(self):
        self.assertEqual(core_policy.decide({"kind": "type", "label": "şifre alanı"})["verdict"], "forbid")


class WorldEventWiring(unittest.TestCase):
    def test_command_reaches_dispatch(self):
        resolved = fast_commands.resolve("dünya olayları")
        self.assertEqual(resolved[0], "world_events")


if __name__ == "__main__":
    unittest.main()
