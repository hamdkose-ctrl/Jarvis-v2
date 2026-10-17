"""Tek eylem kuralı (work_modes) ve öğretilmiş kuralların kapsamı."""
import unittest

from modules import learning, work_modes


class ActionRuleTests(unittest.TestCase):
    def test_answer_or_new_request_while_goal_waits(self):
        for text in ('devam et', 'raporu dosyaya yaz', 'masaüstünü düzenle', 'kaydet'):
            with self.subTest(text=text):
                self.assertTrue(work_modes.ends_with_action(text))
        for text in ('evet', 'tübitak kaynaklarını kullan', 'yapay zeka nedir',
                     'yazın tatile nereye gidelim', 'bunu nasıl yaparım'):
            with self.subTest(text=text):
                self.assertFalse(work_modes.ends_with_action(text))

    def test_rule_scope_needs_explicit_scope_phrase(self):
        cases = {
            'Haber araştırırken gerçek kaynağı doğrula.': 'research',
            'Excel görevlerinde hücredeki sonucu doğrula.': 'pc',
            'Mail gönderirken alıcıyı iki kez kontrol et.': 'communication',
            'Kod konusunda önce testi yaz.': 'project',
            'Sesli cevapta kısa konuş': 'global',
            'Cevaplarında kaynak göster': 'global',
            'Jarvis, bana otomatik haklısın deme': 'global',
        }
        for rule, scope in cases.items():
            with self.subTest(rule=rule):
                self.assertEqual(learning.rule_scope(rule), scope)


if __name__ == '__main__':
    unittest.main()
