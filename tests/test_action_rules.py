"""Tek eylem kuralı (brain_actions) ve öğretilmiş kuralların kapsamı."""
import unittest

from modules import brain_actions, learning


class ActionRuleTests(unittest.TestCase):
    def test_answer_or_new_request_while_goal_waits(self):
        for text in ('devam et', 'raporu dosyaya yaz', 'masaüstünü düzenle', 'kaydet'):
            with self.subTest(text=text):
                self.assertTrue(brain_actions.ends_with_action(text))
        for text in ('evet', 'tübitak kaynaklarını kullan', 'yapay zeka nedir',
                     'yazın tatile nereye gidelim', 'bunu nasıl yaparım'):
            with self.subTest(text=text):
                self.assertFalse(brain_actions.ends_with_action(text))

    def test_brain_path_gives_the_same_answer_as_the_single_rule(self):
        # Gerçek yol: Understanding -> reason code -> brain_entry.goal_question_superseded.
        from test_brain_b3b import superseded
        for text in ('devam et', 'raporu dosyaya yaz', 'masaüstünü düzenle', 'kaydet', 'evet'):
            with self.subTest(text=text):
                self.assertEqual(superseded(text), brain_actions.ends_with_action(text))
        # PR3C-2: açıklama sorusu açık Goal sorusunun cevabı değildir; fiil kuralı False derken
        # canonical hüküm tüketimi engeller (EXPLANATION_REQUEST).
        self.assertTrue(superseded('yapay zeka nedir'))
        self.assertFalse(brain_actions.ends_with_action('yapay zeka nedir'))

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
