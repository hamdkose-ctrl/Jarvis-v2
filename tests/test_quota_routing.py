"""Basit sorular ağır görev yoluna gitmez; 429 alan model her çağrıda yeniden denenmez.

Model ve ağ taklittir: canlı Gemini/Groq kotası burada ölçülmez.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import llm, router, work_modes


def _no_model(*_):
    raise AssertionError('router model called')


CHAT = '{"intent":"chat","args":{}}'


class SimpleQuestionRoutingTests(unittest.TestCase):
    def test_reported_simple_questions_stay_in_chat(self):
        # 17 Ekim 2026 raporundaki örnekler: hepsi görev yürütücüsüne gidiyordu.
        for text in ['yapay zeka nedir', 'yazılım nedir', 'kuralları anlat', 'acaba yarın yağmur yağar mı',
                     'kurban bayramı ne zaman', 'açıklar mısın fotosentez nedir', 'HTTP nedir?', 'merhaba nasılsın',
                     'yapay zekanın geleceği hakkında ne düşünüyorsun', 'uygulama geliştirme zor mu', 'ayarlar nerede']:
            with self.subTest(text=text):
                self.assertEqual(work_modes.classify(text), 'chat')
                self.assertEqual(router.classify(text, lambda *_: CHAT)['intent'], 'chat')

    def test_definition_questions_skip_router_model_call(self):
        for text in ['yapay zeka nedir', 'Yazılım nedir?', 'açıklar mısın fotosentez nedir', 'Atatürk kimdir',
                     'empati ne demek']:
            with self.subTest(text=text):
                self.assertEqual(router.classify(text, _no_model), {'intent': 'chat', 'args': {}})

    def test_fresh_or_tool_topics_keep_model_routing(self):
        for text in ['dolar kuru nedir', 'hava durumu nedir', 'bu dosya nedir']:
            with self.subTest(text=text):
                ask = Mock(return_value=CHAT)
                router.classify(text, ask)
                ask.assert_called_once()

    def test_explicit_freshness_beats_definition_phrasing(self):
        # Faz 4: "son/güncel/bugünkü" gibi açık tazelik işareti, "nedir" tanım kalıbını bastırır;
        # soru güncel-görev yoluna gider, sade model sınıflandırmasına düşmez.
        for text in ['son haber nedir', 'bugünkü dolar kuru nedir', 'güncel altın fiyatı nedir']:
            with self.subTest(text=text):
                self.assertEqual(work_modes.classify(text), 'do')
                ask = Mock(return_value=CHAT)
                self.assertEqual(router.classify(text, ask)['intent'], 'task')
                ask.assert_not_called()

    def test_pure_definition_without_freshness_stays_model_or_chat(self):
        # Tazelik işareti olmayan sade tanım soruları güncel-görev yoluna zorlanmaz.
        for text in ['dolar nedir', 'kur nedir', 'nvidia nedir']:
            with self.subTest(text=text):
                self.assertFalse(work_modes.fresh_external(text))
                self.assertFalse(router._fresh_research_request(text))

    def test_real_action_requests_still_become_tasks(self):
        for text in ['Ayarları aç ve Bluetooth’u kapat', 'Araştırıp rapor hazırla', 'Araştır ve belge üret',
                     'Toplama dosyasını oluştur ve test et', 'raporu kaydet', 'dosyayı kaydeder misin',
                     'bunu Excel’e dönüştürür müsün', 'maili gönderebilir misin', 'dosyayı taşıyıp adını değiştir',
                     'Excel’i açıp A1 hücresine Merhaba yaz', 'rapor hazırlamanı istiyorum', 'kodu düzelt',
                     'İstanbul güncel haberler nelerdir']:
            with self.subTest(text=text):
                self.assertEqual(work_modes.classify(text), 'do')
                self.assertEqual(router.classify(text, lambda *_: CHAT)['intent'], 'task')


class _Chat:
    body = {'error': {'message': 'Quota exceeded PerMinute', 'status': 'RESOURCE_EXHAUSTED'}}

    def __init__(self, sent, model):
        self.sent, self.model = sent, model

    def send_message(self, prompt):
        self.sent.append(self.model)
        raise llm.errors.ClientError(429, self.body)


class RateLimitMemoryTests(unittest.TestCase):
    def setUp(self):
        self.sent, self.sleeps, self.user = [], [], 'alice'
        cli = SimpleNamespace(chats=SimpleNamespace(create=lambda model, config, history: _Chat(self.sent, model)))
        for target, name, kwargs in [
            (llm, '_cli', {'return_value': cli}), (llm, 'provider', {'return_value': 'gemini'}),
            (llm, 'model_names', {'return_value': ['lite', 'flash']}), (llm, 'user_groq_key', {'return_value': ''}),
            (llm, '_ollama_task', {'side_effect': llm.LocalModelError('yok')}),
            (llm, 'current_user', {'side_effect': lambda: self.user}),
            (llm, '_rate_limited', {'new': {}}), (llm, '_fallback_states', {'new': {}}),
            (llm.time, 'sleep', {'side_effect': self.sleeps.append}),
        ]:
            p = patch.object(target, name, **kwargs); p.start(); self.addCleanup(p.stop)
        p = patch.object(llm, 'privacy', SimpleNamespace(mode=lambda: 'normal', redact=lambda t, **_: t))
        p.start(); self.addCleanup(p.stop)
        llm.take_route(); self.addCleanup(llm.take_route)

    def ask(self):
        with self.assertRaises(llm.errors.ClientError):
            llm.ask('yapay zeka nedir', 'sistem')

    def test_429_model_is_not_retried_or_slept_on(self):
        self.ask()
        self.assertEqual(self.sent, ['lite', 'flash'])   # eskiden lite, flash, flash, flash + 1 ve 2 sn bekleme
        self.assertEqual(self.sleeps, [])

    def test_following_calls_skip_limited_models_until_wait_ends(self):
        self.ask(); self.ask(); self.ask()
        self.assertEqual(self.sent, ['lite', 'flash'])
        with patch.object(llm.time, 'monotonic', return_value=llm.time.monotonic() + 61):
            self.ask()
        self.assertEqual(self.sent, ['lite', 'flash', 'lite', 'flash'])

    def test_gemini_429_uses_retry_delay_from_error_body(self):
        retry = {'error': {'message': 'Quota exceeded PerMinute', 'status': 'RESOURCE_EXHAUSTED',
                           'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '300s'}]}}
        with patch.object(_Chat, 'body', retry):
            self.ask()
        until = min(v[0] for v in llm._rate_limited.values())
        self.assertAlmostEqual(until - llm.time.monotonic(), 300, delta=3)   # eskiden hep 60 sn

    def test_gemini_daily_quota_ignores_short_retry_delay(self):
        daily = {'error': {'message': 'Quota exceeded PerDay', 'status': 'RESOURCE_EXHAUSTED',
                           'details': [{'retryDelay': '20s'}]}}
        with patch.object(_Chat, 'body', daily):
            self.ask()
        until = min(v[0] for v in llm._rate_limited.values())
        self.assertAlmostEqual(until - llm.time.monotonic(), 3600, delta=3)

    def test_limit_is_per_user(self):
        self.ask()
        self.user = 'bob'
        self.ask()
        self.assertEqual(self.sent, ['lite', 'flash', 'lite', 'flash'])

    def test_daily_quota_waits_longer(self):
        self.assertEqual(llm._limit_seconds(True), 3600)
        self.assertEqual(llm._limit_seconds(False), 60)
        self.assertEqual(llm._limit_seconds(False, '12'), 12)
        self.assertEqual(llm._limit_seconds(False, 'bozuk'), 60)


class GroqRateLimitMemoryTests(unittest.TestCase):
    def setUp(self):
        for name, kwargs in [('GROQ_MODELS', {'new': ['a', 'b']}), ('_fallback_states', {'new': {}}),
                             ('_rate_limited', {'new': {}}), ('groq_model', {'return_value': 'a'}),
                             ('current_user', {'return_value': 'alice'}), ('user_groq_key', {'return_value': 'k'})]:
            p = patch.object(llm, name, **kwargs); p.start(); self.addCleanup(p.stop)
        from modules import smart_router
        p = patch.object(smart_router, 'settings', return_value={'cloud_free_confirmed': True}); p.start(); self.addCleanup(p.stop)
        llm.take_route(); self.addCleanup(llm.take_route)

    def test_groq_429_uses_retry_after_and_skips_model_next_call(self):
        limited = Mock(status_code=429, headers={'retry-after': '20'}, text='Rate limit reached on tokens per minute')
        with patch.object(llm.requests, 'post', return_value=limited) as post:
            with self.assertRaises(llm.CloudError): llm._groq([], '', 100)
            with self.assertRaises(llm.CloudError): llm._groq([], '', 100)
        self.assertEqual(post.call_count, 2)   # ikinci çağrı hiç istek atmadı
        until = max(v[0] for v in llm._rate_limited.values())
        self.assertAlmostEqual(until - llm.time.monotonic(), 20, delta=2)


if __name__ == '__main__':
    unittest.main()
