"""Kullanıcıya özel sağlayıcı/Groq/yerel model seçimi ve kullanım sınırı gözlemi.

Ağ ve model taklittir; gerçek Groq başlıkları ve Gemini usage_metadata canlı denenmedi.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import llm, usage_meter, user_models


class UserModelChoiceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        p = patch.object(user_models, 'DATA_DIR', self.root); p.start(); self.addCleanup(p.stop)
        self.user = 'hamdi'
        self.settings = {'provider': 'gemini', 'groq_model': 'openai/gpt-oss-20b', 'ollama_model': 'llama3.2'}
        for target, name, kwargs in [
            (llm, 'current_user', {'side_effect': lambda: self.user}),
            (llm, 'load_settings', {'side_effect': lambda: dict(self.settings)}),
            (llm, 'save_settings', {'side_effect': lambda **kw: self.settings.update(kw)}),
            (llm, 'user_groq_key', {'return_value': 'gsk-test'}),
            (llm.privacy, 'mode', {'return_value': 'normal'}),
        ]:
            p = patch.object(target, name, **kwargs); p.start(); self.addCleanup(p.stop)

    def test_without_choice_installation_settings_apply(self):
        self.assertEqual(llm.provider(), 'gemini')
        self.assertEqual(llm.groq_model(), 'openai/gpt-oss-20b')
        self.assertEqual(llm.provider_configuration()['model'], 'llama3.2')

    def test_choice_is_per_user_and_does_not_touch_global_provider(self):
        llm.set_provider('groq', 'qwen/qwen3.8-27b')
        self.assertEqual(llm.provider(), 'groq')
        self.assertEqual(llm.groq_model(), 'qwen/qwen3.8-27b')
        self.assertEqual(self.settings['provider'], 'gemini')       # genel ayar değişmedi
        self.assertEqual(self.settings['groq_model'], 'openai/gpt-oss-20b')
        self.user = 'hasan'
        self.assertEqual(llm.provider(), 'gemini')
        self.assertEqual(llm.groq_model(), 'openai/gpt-oss-20b')
        llm.set_provider('ollama', 'qwen2.5:7b')
        self.assertEqual(llm.provider(), 'ollama')
        self.assertEqual(llm.provider_configuration()['model'], 'qwen2.5:7b')
        self.user = 'hamdi'
        self.assertEqual(llm.provider(), 'groq')
        self.assertEqual(llm.provider_configuration()['model'], 'llama3.2')

    def test_choose_model_keeps_provider_and_gemini_order(self):
        user_models.save('hamdi', ['gemini-a', 'gemini-b'])
        llm.set_provider('gemini')
        llm.choose_model('hamdi', 'ollama', 'llama3.2:3b')
        llm.choose_model('hamdi', 'groq', 'openai/gpt-oss-120b')
        self.assertEqual(llm.provider(), 'gemini')
        self.assertEqual(user_models.get('hamdi', ['x']), ['gemini-a', 'gemini-b'])
        self.assertEqual(user_models.choice('hamdi'),
                         {'provider': 'gemini', 'groq_model': 'openai/gpt-oss-120b', 'local_model': 'llama3.2:3b'})
        user_models.save('hamdi', ['gemini-c'])                      # Gemini kaydı diğer seçimleri silmez
        self.assertEqual(user_models.choice('hamdi')['local_model'], 'llama3.2:3b')

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            llm.choose_model('hamdi', 'openai', 'gpt')               # ücretli model buradan seçilmez
        with self.assertRaises(ValueError):
            llm.choose_model('hamdi', 'ollama', 'kötü model; rm')
        with self.assertRaises(ValueError):
            user_models.save_choice('../kacis', provider='groq')
        with self.assertRaises(ValueError):
            user_models.save_choice('hamdi', provider='bilinmeyen')
        self.assertEqual(user_models.choice('hamdi'), {})

    def test_groq_without_key_is_refused_before_saving(self):
        with patch.object(llm, 'user_groq_key', return_value=''):
            with self.assertRaises(ValueError):
                llm.set_provider('groq')
        self.assertEqual(user_models.choice('hamdi'), {})

    def test_corrupt_record_falls_back_and_is_repaired(self):
        (self.root / 'models').mkdir(parents=True)
        (self.root / 'models' / 'hamdi.json').write_text('[bozuk', encoding='utf-8')
        self.assertEqual(llm.provider(), 'gemini')
        self.assertEqual(user_models.get('hamdi', ['d']), ['d'])
        user_models.save_choice('hamdi', provider='ollama')
        self.assertEqual(llm.provider(), 'ollama')

    def test_local_privacy_mode_still_forces_ollama(self):
        user_models.save_choice('hamdi', provider='groq')
        with patch.object(llm.privacy, 'mode', return_value='yerel'):
            self.assertEqual(llm.provider(), 'ollama')

    def test_no_user_writes_installation_setting(self):
        self.user = None
        llm.set_provider('ollama', 'mistral')
        self.assertEqual(self.settings['provider'], 'ollama')
        self.assertEqual(self.settings['ollama_model'], 'mistral')


class UsageLimitTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        p = patch.object(usage_meter, '_dir', return_value=self.dir); p.start(); self.addCleanup(p.stop)
        p = patch.object(usage_meter, '_owner', return_value='alice'); p.start(); self.addCleanup(p.stop)

    def rows(self):
        return [json.loads(x) for x in (self.dir / 'alice.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_tokens_from_each_provider_format(self):
        self.assertEqual(usage_meter.tokens_from({'usage': {'prompt_tokens': 12, 'completion_tokens': 3}}), (12, 3))
        self.assertEqual(usage_meter.tokens_from({'prompt_eval_count': 7, 'eval_count': 2}), (7, 2))
        meta = SimpleNamespace(prompt_token_count=40, candidates_token_count=9)
        self.assertEqual(usage_meter.tokens_from(SimpleNamespace(usage_metadata=meta)), (40, 9))
        empty = SimpleNamespace(prompt_token_count=40, candidates_token_count=None)
        self.assertEqual(usage_meter.tokens_from(SimpleNamespace(usage_metadata=empty)), (40, 0))
        self.assertIsNone(usage_meter.tokens_from({'choices': []}))
        self.assertIsNone(usage_meter.tokens_from(Mock()))           # taklit yanıt token uydurmaz

    def test_tokens_are_written_only_when_reported(self):
        usage_meter.record('groq', 'g1', 10, 5, tokens=(4, 2), source='t')
        usage_meter.record('groq', 'g1', 10, 5, source='t')
        usage_meter.record('groq', 'g1', 10, 5, tokens=('4', None), source='t')
        rows = self.rows()
        self.assertEqual((rows[0]['ti'], rows[0]['to']), (4, 2))
        self.assertNotIn('ti', rows[1]); self.assertNotIn('ti', rows[2])
        text = usage_meter.summary('alice')
        self.assertIn('Groq: 3 çağrı, 6 token (1 çağrıda bildirildi)', text)

    def test_groq_limit_headers_are_observed_and_summarised(self):
        usage_meter.record('groq', 'g1', 10, 5, tokens=(4, 2), source='t')
        headers = {'x-ratelimit-limit-requests': '1000', 'x-ratelimit-remaining-requests': '50',
                   'x-ratelimit-limit-tokens': '8000', 'x-ratelimit-remaining-tokens': '7990',
                   'x-ratelimit-reset-requests': '2m59.56s'}
        usage_meter.observe_limits('groq', 'g1', headers)
        seen = usage_meter.limits('alice')['groq']['g1']
        self.assertEqual((seen['req_left'], seen['req_limit'], seen['req_reset']), (50, 1000, '2m59.56s'))
        text = usage_meter.summary('alice')
        self.assertIn('Groq · g1: kalan 50/1.000 istek (günlük), kalan 7.990/8.000 token (dakikalık)', text)
        self.assertIn('sınıra yakın', text)

    def test_missing_or_mock_headers_write_nothing(self):
        usage_meter.observe_limits('groq', 'g1', {})
        usage_meter.observe_limits('groq', 'g1', Mock())
        usage_meter.observe_limits('groq', 'g1', None)
        self.assertEqual(usage_meter.limits('alice'), {})
        self.assertFalse((self.dir / 'alice.limits.json').exists())

    def test_groq_call_records_tokens_and_limits(self):
        reply = Mock(status_code=200, headers={'x-ratelimit-limit-requests': '1000', 'x-ratelimit-remaining-requests': '999'},
                     json=lambda: {'choices': [{'message': {'content': 'tamam'}}],
                                   'usage': {'prompt_tokens': 11, 'completion_tokens': 1}})
        with patch.object(llm, 'user_groq_key', return_value='k'), patch.object(llm, 'groq_model', return_value='g1'), \
                patch.object(llm, 'current_user', return_value='alice'), patch.object(llm, '_fallback_states', {}), \
                patch('modules.smart_router.settings', return_value={}), \
                patch.object(llm.requests, 'post', return_value=reply):
            self.assertEqual(llm._groq([{'role': 'user', 'content': 'soru'}], '', 20), 'tamam')
        row = self.rows()[-1]
        self.assertEqual((row['p'], row['ti'], row['to']), ('groq', 11, 1))
        self.assertEqual(usage_meter.limits('alice')['groq']['g1']['req_left'], 999)


if __name__ == '__main__':
    unittest.main()
