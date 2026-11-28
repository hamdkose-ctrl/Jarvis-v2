"""Durum satırı: sağlayıcı, model, bugünün turları ve telefon durumu tek satırda."""
import unittest
from unittest.mock import patch

from modules import status_line


class StatusLineTests(unittest.TestCase):
    def setUp(self):
        status_line._CACHE.clear()

    def test_groq_line_names_provider_model_turns_and_phone(self):
        llm = {"provider": "groq", "groq": {"key": True, "model": "llama-3.3-70b"}, "models": ["a"], "active": 0}
        text = status_line.build(llm, {"running": False}, (12, 1))
        self.assertEqual(text, "Groq · llama-3.3-70b · bugün 12 tur (1 hata) · telefon kapalı")

    def test_gemini_line_uses_the_active_model_name(self):
        llm = {"provider": "gemini", "key": True, "models": ["gemini-3-flash", "gemini-3-pro"], "active": 1}
        self.assertIn("Gemini · gemini-3-pro", status_line.build(llm, {"running": True}, None))
        self.assertIn("telefon açık", status_line.build(llm, {"running": True}, None))

    def test_missing_key_is_said_instead_of_a_model_name(self):
        text = status_line.build({"provider": "gemini", "key": False}, {}, (3, 0))
        self.assertTrue(text.startswith("Gemini anahtarı yok"))
        self.assertIn("bugün 3 tur", text)
        self.assertNotIn("hata", text)

    def test_no_data_is_not_invented(self):
        text = status_line.build({}, {}, None)
        self.assertEqual(text, "Model · telefon kapalı")

    def test_today_reads_turn_metrics_once_and_caches(self):
        rows = [{"r": "ok"}, {"r": "hata"}, {"r": "ok"}]
        with patch("modules.turn_metrics.rows", return_value=rows) as patched:
            self.assertEqual(status_line.today("hamdi"), (3, 1))
            self.assertEqual(status_line.today("hamdi"), (3, 1))
        self.assertEqual(patched.call_count, 1)

    def test_a_broken_metric_store_leaves_an_honest_zero(self):
        with patch("modules.turn_metrics.rows", side_effect=OSError("bozuk")):
            self.assertEqual(status_line.today("hamdi"), (0, 0))

    def test_snapshot_line_uses_snapshot_parts(self):
        snap = {"llm": {"provider": "ollama", "local_model": "qwen3:8b"}, "phone": {"running": True}}
        with patch("modules.turn_metrics.rows", return_value=[{"r": "ok"}]):
            text = status_line.for_snapshot(snap, "hamdi")
        self.assertEqual(text, "Yerel · qwen3:8b · bugün 1 tur · telefon açık")

    def test_snapshot_line_never_raises(self):
        with patch.object(status_line, "build", side_effect=RuntimeError("bozuk")):
            self.assertEqual(status_line.for_snapshot({}, "hamdi"), "")


if __name__ == "__main__":
    unittest.main()
