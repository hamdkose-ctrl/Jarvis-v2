"""Sohbet cümlesinde geçersiz eylem atfı: tur düşmez, bir kez daha sorulur.

Canlı kusur (26 Kasım 15:20): "İstanbul dersin" → "doğrulayamadım, hiçbir işlem başlatmadım".
Kök neden: model var olmayan bir eyleme atıf yaptı (ACTION_REFERENCE_INVALID) ve zarf
tümüyle reddedildi. Doğrulama gevşetilmedi; yalnız **bir** düzeltici tekrar eklendi.
"""
import unittest

from modules import brain_model_understanding as brain


class RetryDecision(unittest.TestCase):
    def test_invalid_action_retries_exactly_once(self):
        diagnostic = {"reason_code": "ACTION_CAPABILITY_UNKNOWN"}
        self.assertTrue(brain.retry_after_invalid_action(diagnostic, 0))
        self.assertFalse(brain.retry_after_invalid_action(diagnostic, 1))

    def test_other_rejections_do_not_retry(self):
        for code in ("GOAL_SHAPE_INVALID", "ARGUMENTS_INVALID", "ACTION_REFERENCE_INVALID"):
            self.assertFalse(brain.retry_after_invalid_action({"reason_code": code}, 0))

    def test_empty_diagnostic_does_not_retry(self):
        self.assertFalse(brain.retry_after_invalid_action({}, 0))

    def test_correction_names_the_chat_escape(self):
        self.assertIn("chat", brain.CHAT_CORRECTION)
        self.assertIn("actions=[]", brain.CHAT_CORRECTION)


if __name__ == "__main__":
    unittest.main()
