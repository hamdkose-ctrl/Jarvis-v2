"""Kural/mevzuat taze dış veri sayılır (B4-4)."""
import unittest

from modules import brain_core_map, brain_understanding
from modules.brain_contracts import ActiveContext, RequestKind


def decide(text: str):
    semantic = brain_understanding.understand(
        owner="hamdi", request_id="rid-mevzuat", text=text,
        active_context=ActiveContext(owner="hamdi", request_id="rid-mevzuat"),
        candidates=(), references=())
    return semantic, brain_core_map.core_plan(semantic.capability_hint, semantic.arguments)


class RegulationFreshnessTests(unittest.TestCase):
    def test_guncel_yonetmelik_arastirmaya_gider(self):
        for text in ("güncel yönetmelik nelerdir", "son tebliğ değişikliklerini anlat",
                     "2026 mevzuat değişiklikleri neler"):
            with self.subTest(text=text):
                self.assertTrue(brain_understanding._needs_fresh_external_data(text))
                self.assertEqual(decide(text)[1][0], "task")

    def test_tanım_sorusu_statiktir(self):
        for text in ("yönetmelik nedir", "mevzuat ne demek"):
            with self.subTest(text=text):
                self.assertFalse(brain_understanding._needs_fresh_external_data(text))
                self.assertIsNone(decide(text)[1])

    def test_kural_dışı_cümle_etkilenmez(self):
        self.assertFalse(brain_understanding._needs_fresh_external_data("saat kaç oldu alarm kur"))


if __name__ == "__main__":
    unittest.main()
