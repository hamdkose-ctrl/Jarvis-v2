import unittest
from contextlib import ExitStack
from unittest.mock import patch
from modules import goal_executor


class NewsErrorRenderTests(unittest.TestCase):
    def job(self, messages, feedback):
        return {'state': 'blocked', 'goals': [], 'steps': [
                    {'id': str(i), 'tool': 'research', 'state': 'failed'} for i in range(len(messages))],
                'outputs': {str(i): {'state': 'failed', 'text': text} for i, text in enumerate(messages)},
                'feedback': feedback}

    def test_same_step_and_feedback_error_is_shown_once(self):
        job = self.job(['Kaynak HTTP error.', 'Kaynak HTTP error.'], [' kayNAK   HTTP   ERROR. '])
        rendered = ' '.join(goal_executor.render(job).casefold().split())
        self.assertEqual(rendered.count('kaynak http error.'), 1)

    def test_different_errors_remain_visible(self):
        rendered = goal_executor.render(self.job(['Kaynak açılamadı.'], ['Başka haber bulunamadı.']))
        self.assertIn('Kaynak açılamadı.', rendered)
        self.assertIn('Başka haber bulunamadı.', rendered)


class OllamaRouteTextTests(unittest.TestCase):
    def setUp(self):
        from modules import llm
        self.llm = llm
        self.notes = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in [('_cli', object()), ('user_groq_key', ''), ('current_user', 'alice')]:
            self.stack.enter_context(patch.object(llm, name, return_value=value))
        self.stack.enter_context(patch.object(llm, '_need_cloud', side_effect=lambda text: text))
        self.stack.enter_context(patch.object(llm.privacy, 'mode', return_value='normal'))
        self.stack.enter_context(patch.object(llm, 'note_route', side_effect=lambda text, ok: self.notes.append(text)))
        self.stack.enter_context(patch.object(llm.requests, 'post', side_effect=AssertionError('Gerçek ağ yasak')))

    def error(self, unavailable):
        error = self.llm.LocalModelError('Yerel model işlemi başarısız.')
        if unavailable:
            error.__cause__ = ConnectionRefusedError(111, 'Connection refused')
        return error

    def test_gemini_quota_has_no_cross_provider_fallback(self):
        llm = self.llm
        quota = llm.errors.ClientError(429, {'error': {'message': 'SECRET_FAKE_PROVIDER_DETAIL', 'code': 429, 'status': 'RESOURCE_EXHAUSTED'}})
        def timed(name, function):
            if name == 'gemini':
                raise quota
            raise AssertionError('Gemini hatasından sonra başka sağlayıcı denenmemeli: ' + name)
        with patch.object(llm, '_timed', side_effect=timed), patch.object(llm, '_ollama_task', side_effect=AssertionError('Ollama çağrılmamalı')), patch.object(llm, '_groq', side_effect=AssertionError('Groq çağrılmamalı')):
            with self.assertRaises(llm.errors.ClientError) as raised:
                llm._send_provider('gemini', 'Haber isteği', '', 100, [])
        from modules import failure_policy
        text = failure_policy.explain(raised.exception)
        self.assertIn('kullanım sınırı', text)
        self.assertNotIn('429', text)
        self.assertNotIn('SECRET_FAKE_PROVIDER_DETAIL', text)

    def test_ollama_failure_is_not_retried_on_gemini(self):
        def timed(name, function):
            if name == 'gemini':
                raise AssertionError('Ollama hatasında Gemini denenmemeli')
            return function()
        with patch.object(self.llm, '_timed', side_effect=timed), patch.object(self.llm, '_ollama_task', side_effect=self.error(True)):
            with self.assertRaises(self.llm.LocalModelError):
                self.llm._send_provider('ollama', 'Haber', '', 100, [])

    def test_timeout_is_not_claimed_to_be_missing_service(self):
        from modules import ollama_hint
        error = self.llm.LocalModelError('Yerel model işlemi başarısız.')
        error.__cause__ = self.llm.requests.ReadTimeout('Taklit süre aşımı')
        self.assertFalse(ollama_hint.unavailable(error))


if __name__ == '__main__':
    unittest.main()
