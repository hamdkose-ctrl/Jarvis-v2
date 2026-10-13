import unittest
from unittest.mock import Mock

from modules.router import classify


def _no_llm(*_args, **_kwargs):
    raise AssertionError("Bu komut hızlı yoldan sınıflandırılmalı; LLM router çağrılmamalı")


class RouterFastPathTests(unittest.TestCase):
    def test_context_reaches_classifier_without_replacing_live_reference_context(self):
        model = Mock(return_value='{"intent":"open_app","args":{"name":"paint"}}')
        result = classify('onu aç', model, context='Önceki hedef: Paint')
        self.assertEqual(result['args']['name'], 'paint')
        self.assertIn('Önceki hedef: Paint', model.call_args.args[1])

    def test_invalid_or_unsupported_action_cannot_become_chat_promise(self):
        for response in ('not json', '{"intent":"shell","args":{}}', '{"intent":"chat","args":{}}'):
            with self.subTest(response=response):
                self.assertEqual(classify('bunu düzelt', lambda *_: response)['intent'], 'clarify')

    def test_instruction_question_stays_chat(self):
        self.assertEqual(classify('Chrome nasıl açılır?', lambda *_: '{"intent":"chat"}')['intent'], 'chat')
    def test_greeting_is_chat(self):
        self.assertEqual(classify("merhaba", _no_llm)["intent"], "chat")

    def test_screen_analysis_is_not_status(self):
        result = classify("ekranı analiz et", _no_llm)
        self.assertEqual(result["intent"], "screen_analyze")
        self.assertEqual(result["args"].get("question"), "")

    def test_system_status_is_separate(self):
        self.assertEqual(classify("sistem durumu", _no_llm)["intent"], "status")



if __name__ == "__main__":
    unittest.main()
