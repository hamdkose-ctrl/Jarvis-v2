"""Türkçe büyük harf komutları: "HEDEF İPTAL" iptal eder, yeni iş açmaz.

Canlı hata (22 Kasım 2026, 16:05): sesli "HEDEF İPTAL" iptal etmedi; "İPTAL"
adında yeni bir hedef açtı. Sebep: str.casefold() 'İ' harfini 'i' + birleşik
nokta yapıyor, bu yüzden komut tablosu eşleşmiyor ve `hedef <konu>` kuralı
devreye giriyordu. Küçük harf "hedef iptal" doğru çalışıyordu.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import goal_executor


class CommandFoldingTests(unittest.TestCase):
    def test_turkish_uppercase_is_folded_like_lowercase(self):
        for written in ("HEDEF İPTAL", "hedef iptal", "Hedef İptal", "  HEDEF   İPTAL.  "):
            self.assertEqual(goal_executor._low(written), "hedef iptal")
        self.assertEqual(goal_executor._low("HEDEF DURUMU"), "hedef durumu")
        self.assertEqual(goal_executor._low("İPTAL"), "iptal")
        # casefold tek başına bu eşitliği sağlamıyor (regresyonun kökü).
        self.assertNotEqual("HEDEF İPTAL".casefold(), "hedef iptal")


class GoalCancelCommandTests(unittest.TestCase):
    def _runtime(self):
        profile = SimpleNamespace(slug="hamdi", data={})
        return SimpleNamespace(profile=profile, pc_profile=lambda: profile, emit=Mock())

    def test_uppercase_cancel_cancels_instead_of_creating_a_job(self):
        job = {"id": "j1", "owner": "hamdi", "request": "Yapay zeka makaleleri araştır",
               "state": "paused", "goals": [], "steps": [], "outputs": {}}
        with patch.object(goal_executor, "latest", return_value=job), \
             patch.object(goal_executor, "_save"), \
             patch.object(goal_executor, "render", return_value="Hedef iptal edildi."), \
             patch.object(goal_executor, "run") as run:
            reply = goal_executor.handle(self._runtime(), "HEDEF İPTAL")
        self.assertEqual(job["state"], "cancelled")
        self.assertEqual(reply, "Hedef iptal edildi.")
        run.assert_not_called()

    def test_uppercase_cancel_without_open_goal_reports_and_creates_nothing(self):
        with patch.object(goal_executor, "latest", return_value=None), \
             patch.object(goal_executor, "_save"), \
             patch.object(goal_executor, "run") as run:
            reply = goal_executor.handle(self._runtime(), "HEDEF İPTAL")
        self.assertEqual(reply, "Kayıtlı hedef yok.")
        run.assert_not_called()

    def test_unprefixed_uppercase_cancel_also_reaches_the_goal(self):
        job = {"id": "j2", "owner": "hamdi", "request": "haber", "state": "running",
               "goals": [], "steps": [], "outputs": {}}
        with patch.object(goal_executor, "latest", return_value=job), \
             patch.object(goal_executor, "_save"), \
             patch.object(goal_executor, "render", return_value="Hedef iptal edildi."), \
             patch.object(goal_executor, "run") as run:
            goal_executor.handle(self._runtime(), "İPTAL")
        self.assertEqual(job["state"], "cancelled")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
