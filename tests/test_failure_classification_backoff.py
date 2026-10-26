"""Faz 1-A: geçici 429 / kalıcı kota / kimlik / ağ / yerel model ayrımı ve sınırlı artan bekleme.

Ağ, model ve gerçek bekleme yoktur: sağlayıcı hataları taklit edilir, uyku sahte saatle sayılır.
"""
import unittest
from unittest.mock import Mock, patch

from modules import failure_policy as fp, llm


class Http(RuntimeError):
    def __init__(self, code, text=''):
        super().__init__(text)
        self.status_code = code


class ClassificationTests(unittest.TestCase):
    def test_transient_rate_limit_and_permanent_quota_are_separate(self):
        minute = Http(429, 'Quota exceeded for metric GenerateRequestsPerMinutePerProjectPerModel; '
                           'You exceeded your current quota, please check your plan and billing details')
        rows = [
            (minute, fp.RATE_LIMIT),
            (Http(429, ''), fp.RATE_LIMIT),
            (Http(429, 'Quota exceeded GenerateRequestsPerDayPerProjectPerModel-FreeTier'), fp.QUOTA_EXHAUSTED),
            (RuntimeError('Rate limit reached for model on tokens per day (TPD): Limit 100000'), fp.QUOTA_EXHAUSTED),
            (RuntimeError('429 insufficient_quota'), fp.QUOTA_EXHAUSTED),
        ]
        for exc, category in rows:
            with self.subTest(text=str(exc)[:40]):
                self.assertEqual(fp.classify(exc), category)
        self.assertNotEqual(fp.explain(minute), fp.explain(rows[2][0]))
        self.assertIn('geçici', fp.explain(minute))
        self.assertIn('günlük kota', fp.explain(rows[2][0]))
        self.assertNotIn('doldu', fp.explain(minute))
        self.assertEqual(fp.reason_code(rows[2][0]), 'PROVIDER_QUOTA_EXHAUSTED')
        self.assertEqual(fp.legacy_kind(rows[2][0]), 'quota')
        self.assertGreater(fp.cooldown_seconds('gemini', rows[2][0]), fp.cooldown_seconds('gemini', minute))

    def test_each_failure_kind_has_its_own_user_reason(self):
        rows = {
            fp.RATE_LIMIT: Http(429, 'PRIVATE'),
            fp.QUOTA_EXHAUSTED: Http(429, 'PerDay PRIVATE'),
            fp.AUTH: Http(401, 'PRIVATE'),
            fp.DNS: OSError('Name or service not known PRIVATE'),
            fp.NETWORK: ConnectionRefusedError(111, 'Connection refused PRIVATE'),
            fp.TIMEOUT: TimeoutError('PRIVATE timed out'),
            fp.LOCAL_MODEL: llm.LocalModelError(llm.ollama_hint.need('Yerel model')),
        }
        texts = {}
        with patch.object(llm.ollama_hint, 'internet_up', return_value=True):
            for category, exc in rows.items():
                with self.subTest(category=category):
                    self.assertEqual(fp.classify(exc), category)
                    texts[category] = fp.user_message(exc)
                    self.assertNotIn('PRIVATE', texts[category])
        self.assertEqual(len(set(texts.values())), len(texts))

    def test_groq_missing_or_invalid_key_is_auth(self):
        for text in ('Bu kullanıcının Groq API anahtarı yok. Bağlantılar sayfasından ekle.',
                     'Groq API anahtarı geçersiz ya da yetkisiz.'):
            with self.subTest(text=text):
                self.assertEqual(fp.classify(llm.LocalModelError(text)), fp.AUTH)

    def test_local_model_missing_names_pull_command_without_raw_text(self):
        exc = llm.LocalModelError("Ollama'da “qwen2.5:7b” modeli yok. Terminalde `ollama pull qwen2.5:7b` yaz.")
        self.assertEqual(fp.classify(exc), fp.LOCAL_MODEL)
        self.assertIn('ollama pull qwen2.5:7b', fp.explain(exc))
        self.assertEqual(fp.reason_code(exc), 'PROVIDER_LOCAL_MODEL')
        self.assertEqual(fp.recovery_class(exc), 'user_action_required')

    def test_non_provider_error_keeps_specific_message(self):
        self.assertEqual(fp.user_message(ValueError('Desteklenmeyen görüntü biçimi.')), 'Desteklenmeyen görüntü biçimi.')

    def test_ask_image_soft_failure_does_not_leak_raw_provider_text(self):
        with patch.object(llm, 'provider', return_value='gemini'), \
             patch.object(llm.privacy, 'mode', return_value='normal'), \
             patch.object(llm, '_cli', return_value=object()), \
             patch('PIL.Image.open', side_effect=Http(429, 'PerDay key=PRIVATE')):
            text = llm.ask_image('missing.png', 'ne var?')
        self.assertNotIn('PRIVATE', text)
        self.assertIn('günlük kota', text)


class BackoffTests(unittest.TestCase):
    def test_delay_grows_exponentially_and_is_capped(self):
        top = [fp.backoff_delay(n, rand=lambda: 1.0) for n in range(1, 7)]
        self.assertEqual(top, [1.0, 2.0, 4.0, 8.0, 8.0, 8.0])
        low = [fp.backoff_delay(n, rand=lambda: 0.0) for n in range(1, 4)]
        self.assertEqual(low, [0.5, 1.0, 2.0])

    def test_sleep_checks_cancellation_during_wait(self):
        slept = []
        check = Mock(side_effect=[None, None, RuntimeError('iptal')])
        with self.assertRaises(RuntimeError):
            fp.backoff_sleep(3, check=check, sleep=slept.append, rand=lambda: 1.0)
        self.assertEqual(sum(slept), 0.5)          # 4 sn beklemenin ortasında iptal yakalandı

    def test_only_transient_failures_are_retried_in_place(self):
        self.assertTrue(fp.is_transient(TimeoutError('x')))
        self.assertTrue(fp.is_transient(Http(503, 'x')))
        for exc in (Http(429, 'x'), Http(429, 'PerDay'), Http(401, 'x'), llm.LocalModelError('Ollama yok')):
            self.assertFalse(fp.is_transient(exc))

    def test_gemini_server_error_retries_bounded_with_growing_waits(self):
        calls, waits = [], []

        def call(model):
            calls.append(model)
            raise llm.errors.ServerError(503, {'error': {'message': 'overloaded', 'status': 'UNAVAILABLE'}})

        with patch.object(llm, 'model_names', return_value=['m1']), \
             patch.object(llm, 'current_user', return_value='alice'), \
             patch.object(llm, '_fallback_states', {}), patch.object(llm, '_rate_limited', {}), \
             patch.object(llm.usage_meter, 'record'), \
             patch.object(fp.random, 'random', return_value=1.0), \
             patch.object(llm.time, 'sleep', side_effect=waits.append):
            with self.assertRaises(llm.errors.ServerError):
                llm._with_models(call)
        self.assertEqual(len(calls), llm._MAX_TRIES)
        self.assertEqual(sum(waits), 1.0 + 2.0)    # 1 sn, sonra 2 sn: artan bekleme, sonsuz deneme yok


if __name__ == '__main__':
    unittest.main()
