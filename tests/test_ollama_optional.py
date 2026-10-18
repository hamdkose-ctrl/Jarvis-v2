"""Ollama isteğe bağlıdır: yokluğunda açık Türkçe mesaj, internet yokluğunda tek cümle."""
import unittest
from unittest.mock import patch

import requests

from modules import failure_policy, llm, ollama_hint, privacy, worktrack


class HintTests(unittest.TestCase):
    def test_need_message_names_the_feature_and_where_to_get_ollama(self):
        text = ollama_hint.need('Yalnızca yerel mod')
        self.assertIn('Ollama yüklemelisin', text)
        self.assertIn('ollama.com', text)
        self.assertTrue(text.startswith('Yalnızca yerel mod'))

    def test_dns_failure_with_no_internet_gives_single_sentence(self):
        with patch.object(ollama_hint, '_probe', return_value=False):
            ollama_hint._cache.clear()
            text = failure_policy.explain(requests.ConnectionError('getaddrinfo failed'))
        self.assertEqual(text, 'İnternet bağlantın yok, bağlanınca tekrar dene.')

    def test_dns_failure_with_internet_keeps_old_explanation(self):
        with patch.object(ollama_hint, '_probe', return_value=True):
            ollama_hint._cache.clear()
            text = failure_policy.explain(requests.ConnectionError('getaddrinfo failed'))
        self.assertNotIn('İnternet bağlantın yok', text)

    def test_local_model_failure_is_never_called_internet_loss(self):
        with patch.object(ollama_hint, '_probe', return_value=False):
            ollama_hint._cache.clear()
            self.assertIsNone(ollama_hint.offline_text(llm.LocalModelError('Ollama çalışmıyor')))


class OllamaMissingTests(unittest.TestCase):
    def test_ollama_down_message_tells_user_to_install(self):
        with patch.object(llm.requests, 'post', side_effect=requests.ConnectionError('refused')), \
             patch.object(llm.usage_meter, 'record'):
            with self.assertRaises(llm.LocalModelError) as cm:
                llm._ollama([{'role': 'user', 'content': 'merhaba'}], '', 50)
        self.assertIn('Ollama yüklemelisin', str(cm.exception))

    def test_local_only_mode_without_ollama_says_install(self):
        with patch.object(privacy, 'mode', return_value='yerel'):
            with self.assertRaises(llm.LocalModelError) as cm:
                llm._need_cloud('merhaba')
        self.assertIn('Ollama yüklemelisin', str(cm.exception))

    def test_work_mail_local_ai_without_ollama_keeps_plain_list_and_says_install(self):
        facts = {'recent': [1], 'dated': [], 'vip': [], 'cc_only': 0}
        with patch.object(worktrack, 'facts', return_value=facts), \
             patch.object(worktrack, 'settings', return_value={'ai': 'local'}), \
             patch.object(worktrack, 'prompt_data', return_value='x'), patch.object(worktrack, '_ai', side_effect=llm.LocalModelError('yok')), \
             patch.object(worktrack, '_plain', return_value='DÜZ LİSTE'):
            text = worktrack.report('status')
        self.assertIn('DÜZ LİSTE', text)
        self.assertIn('Ollama yüklemelisin', text)

    def test_work_mail_cloud_ai_failure_has_no_ollama_hint(self):
        facts = {'recent': [1], 'dated': [], 'vip': [], 'cc_only': 0}
        with patch.object(worktrack, 'facts', return_value=facts), \
             patch.object(worktrack, 'settings', return_value={'ai': 'meta'}), \
             patch.object(worktrack, 'prompt_data', return_value='x'), patch.object(worktrack, '_ai', side_effect=RuntimeError('x')), \
             patch.object(worktrack, '_plain', return_value='DÜZ LİSTE'):
            text = worktrack.report('status')
        self.assertEqual(text, 'DÜZ LİSTE')

    def test_vision_without_support_names_the_alternatives(self):
        err = llm.ImageCapabilityError(ollama_hint.IMAGE)
        self.assertIn('Gemini', str(err))
        self.assertIn('Ollama', str(err))


if __name__ == '__main__':
    unittest.main()
