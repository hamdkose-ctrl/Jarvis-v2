"""Sohbet yolu: izin/onay dilenmesi cevaptan çıkarılır."""
import unittest

from modules.tone_guard import strip_permission_bait


class PermissionBaitTests(unittest.TestCase):
    def test_removes_only_the_bait_sentence(self):
        metin = "Bugün hava açık. Komutu çalıştırmam için onay verir misin?"
        self.assertEqual(strip_permission_bait(metin), "Bugün hava açık.")

    def test_removes_the_decision_handback(self):
        metin = "Saat 02:41. Sonraki adımda devam edeyim mi, yoksa kararı sana mı bırakalım?"
        self.assertEqual(strip_permission_bait(metin), "Saat 02:41.")

    def test_keeps_an_answer_without_bait(self):
        metin = "Saat 02:41, Pazar."
        self.assertEqual(strip_permission_bait(metin), metin)

    def test_never_returns_empty(self):
        self.assertEqual(strip_permission_bait("Onay verir misin?"), "Tamam.")


if __name__ == "__main__":
    unittest.main()
