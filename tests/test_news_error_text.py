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
        if unavailable:
            error = self.llm.LocalModelError(self.llm.local_hint())
            error.__cause__ = ConnectionRefusedError(111, 'Connection refused')
            return error
        return self.llm.LocalModelError('Yerel model işlemi başarısız.')

    def gemini_quota(self, error):
        from modules import smart_router
        quota = self.llm.errors.ClientError(429, {'error': {'message': 'SECRET_FAKE_PROVIDER_DETAIL', 'code': 429, 'status': 'RESOURCE_EXHAUSTED'}})
        def callback(provider):
            if provider == 'gemini':
                raise quota
            if provider == 'ollama':
                raise error
            raise AssertionError('Beklenmeyen provider')
        with patch.object(smart_router, 'selection', return_value={'candidates':['gemini','ollama'],'skipped':[]}), \
             patch.object(smart_router, '_free_emergency', return_value=False):
            with self.assertRaises(RuntimeError) as raised:
                smart_router.run('alice','Haber isteği',callback)
        return str(raised.exception) + '\n' + '\n'.join(self.notes)

    def test_connection_refused_after_quota_explains_install(self):
        text = self.gemini_quota(self.error(True))
        self.assertIn('Ollama yüklü değil ya da çalışmıyor', text)
        self.assertNotIn('SECRET_FAKE_PROVIDER_DETAIL', text)

    def test_running_service_error_retains_generic_wording(self):
        text = self.gemini_quota(self.error(False))
        self.assertIn('ollama: çağrı başarısız', text.casefold())
        self.assertNotIn('Ollama yüklü değil', text)

    def test_no_groq_key_means_no_groq_error_and_quota_is_masked(self):
        text = self.gemini_quota(self.error(True))
        self.assertNotIn('Groq', text)
        self.assertNotIn('429', text)
        self.assertNotIn('SECRET_FAKE_PROVIDER_DETAIL', text)

    def test_selected_ollama_strict_execution_never_directly_falls_to_gemini(self):
        with patch.object(self.llm, '_ollama_task', side_effect=self.error(True)), \
             patch.object(self.llm, '_cli', side_effect=AssertionError('Gemini direct fallback yasak')):
            with self.assertRaises(self.llm.LocalModelError):
                self.llm._send('Haber', '', 100, [], 'ollama', True)

    def test_timeout_is_not_claimed_to_be_missing_service(self):
        from modules import ollama_hint
        error = self.llm.LocalModelError('Yerel model işlemi başarısız.')
        error.__cause__ = self.llm.requests.ReadTimeout('Taklit süre aşımı')
        self.assertFalse(ollama_hint.unavailable(error))


if __name__ == '__main__':
    unittest.main()
