"""Basit sorular ağır görev yoluna gitmez; 429 alan model her çağrıda yeniden denenmez.

Model ve ağ taklittir: canlı Gemini/Groq kotası burada ölçülmez.
PR10c: karar artık canonical sınırdadır (Understanding + tek sınıflandırılmış-istek kapısı) ve
hiçbir cümle için model sınıfleyicisi çalışmaz; bu yüzden "kotada model yakma" iddiası burada
doğal olarak sağlanır.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import brain_core_map, brain_understanding, llm,smart_router
from modules.brain_contracts import RequestKind
import test_brain_production_entry as fixtures

RID = 'rid-quota'


def _door(text):
    """Cümlenin canonical kapı kararı: plan doğrulanırsa o, yoksa kapının devir biçimi."""
    return fixtures.door(text, request_id=RID)


class SimpleQuestionRoutingTests(unittest.TestCase):
    def test_reported_simple_questions_stay_in_chat(self):
        # 17 Ekim 2026 raporundaki örnekler: hepsi görev yürütücüsüne gidiyordu.
        for text in ['yapay zeka nedir', 'yazılım nedir', 'kuralları anlat', 'acaba yarın yağmur yağar mı',
                     'kurban bayramı ne zaman', 'açıklar mısın fotosentez nedir', 'HTTP nedir?', 'merhaba nasılsın',
                     'yapay zekanın geleceği hakkında ne düşünüyorsun', 'uygulama geliştirme zor mu', 'ayarlar nerede']:
            with self.subTest(text=text):
                semantic, decision = _door(text)
                self.assertIs(semantic.request_kind, RequestKind.CHAT, text)
                self.assertEqual(decision, {'intent': 'chat', 'args': {}}, text)

    def test_definition_questions_need_no_model_call(self):
        for text in ['yapay zeka nedir', 'Yazılım nedir?', 'açıklar mısın fotosentez nedir', 'Atatürk kimdir',
                     'empati ne demek', 'dolar kuru nedir', 'hava durumu nedir', 'bu dosya nedir']:
            with self.subTest(text=text), patch.object(llm, 'ask', side_effect=AssertionError('model yakılmamalı')):
                self.assertEqual(_door(text)[1], {'intent': 'chat', 'args': {}}, text)

    def test_explicit_freshness_beats_definition_phrasing(self):
        # "son/güncel/bugünkü" gibi açık tazelik işareti, "nedir" tanım kalıbını bastırır:
        # soru canlı veri yoluna gider, sade sohbete düşmez.
        for text in ['son haber nedir', 'güncel altın fiyatı nedir']:
            with self.subTest(text=text):
                semantic, decision = _door(text)
                self.assertEqual(semantic.capability_hint, 'research.search', text)
                self.assertEqual(decision['intent'], 'task', text)
                self.assertEqual(brain_core_map.core_plan(semantic.capability_hint, semantic.arguments),
                                 ('task', {'query': text, 'route': 'PRIVATE'}), text)
        # Finance data is no longer selected by deterministic vocabulary rules. Its production
        # model-proposal and typed-Core path is covered by test_brain_b3_finance_authority.
        semantic, decision = _door('bugünkü dolar kuru nedir')
        self.assertNotEqual(semantic.capability_hint, 'finance.read')
        self.assertNotEqual(decision['intent'], 'finance_read')

    def test_pure_definition_without_freshness_stays_chat(self):
        # Tazelik işareti olmayan sade tanım soruları güncel-görev yoluna zorlanmaz.
        for text in ['dolar nedir', 'kur nedir', 'nvidia nedir']:
            with self.subTest(text=text):
                self.assertFalse(brain_understanding._needs_fresh_external_data(brain_understanding._norm(text)), text)
                self.assertNotEqual(_door(text)[0].capability_hint, 'research.search', text)

    def test_real_action_requests_still_become_tasks(self):
        for text in ['Ayarları aç ve Bluetooth’u kapat', 'Araştırıp rapor hazırla', 'Araştır ve belge üret',
                     'Toplama dosyasını oluştur ve test et', 'raporu kaydet', 'dosyayı kaydeder misin',
                     'bunu Excel’e dönüştürür müsün', 'maili gönderebilir misin', 'dosyayı taşıyıp adını değiştir',
                     'Excel’i açıp A1 hücresine Merhaba yaz', 'rapor hazırlamanı istiyorum', 'kodu düzelt',
                     'İstanbul güncel haberler nelerdir']:
            with self.subTest(text=text):
                self.assertEqual(_door(text)[1]['intent'], 'task', text)


class _Chat:
    body = {'error': {'message': 'Quota exceeded PerMinute', 'status': 'RESOURCE_EXHAUSTED'}}

    def __init__(self, sent, model):
        self.sent, self.model = sent, model

    def send_message(self, prompt):
        self.sent.append(self.model)
        raise llm.errors.ClientError(429, self.body)


class RateLimitMemoryTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for name,value in (('_STORE',Path(folder.name)),('_HEALTH',{})):
            p=patch.object(smart_router,name,value);p.start();self.addCleanup(p.stop)
        plan=smart_router.RoutePlan(tuple(smart_router.ModelSpec('gemini',m) for m in ('lite','flash')),(),2)
        p=patch.object(smart_router,'plan',return_value=plan);p.start();self.addCleanup(p.stop)
        self.sent, self.sleeps, self.user = [], [], 'alice'
        cli = SimpleNamespace(chats=SimpleNamespace(create=lambda model, config, history: _Chat(self.sent, model)))
        for target, name, kwargs in [
            (llm, '_cli', {'return_value': cli}), (llm, 'provider', {'return_value': 'gemini'}),
            (llm, 'model_names', {'return_value': ['lite', 'flash']}), (llm, 'user_groq_key', {'return_value': ''}),
            (llm, 'current_user', {'side_effect': lambda: self.user}),
            (llm, '_rate_limited', {'new': {}}), (llm, '_fallback_states', {'new': {}}),
            (llm.time, 'sleep', {'side_effect': self.sleeps.append}),
        ]:
            p = patch.object(target, name, **kwargs); p.start(); self.addCleanup(p.stop)
        p = patch.object(llm, 'privacy', SimpleNamespace(mode=lambda: 'normal', redact=lambda t, **_: t))
        p.start(); self.addCleanup(p.stop)
        llm.take_route(); self.addCleanup(llm.take_route)

    def ask(self):
        with self.assertRaises(RuntimeError):
            request=smart_router.ModelRequest(owner=self.user)
            smart_router.run_request(request,lambda spec:llm._send_provider(spec.provider,'yapay zeka nedir','sistem',2000,None,model=spec.model))   # Gemini aktarımı; sağlayıcıyı Router seçer

    def test_429_model_is_not_retried_or_slept_on(self):
        self.ask()
        self.assertEqual(self.sent, ['lite', 'flash'])   # eskiden lite, flash, flash, flash + 1 ve 2 sn bekleme
        self.assertEqual(self.sleeps, [])

    def test_following_calls_skip_limited_models_until_wait_ends(self):
        self.ask(); self.ask(); self.ask()
        self.assertEqual(self.sent, ['lite', 'flash'])
        with patch.object(llm.time, 'monotonic', return_value=llm.time.monotonic() + 301):
            self.ask()
        self.assertEqual(self.sent, ['lite', 'flash', 'lite', 'flash'])

    def test_gemini_429_uses_retry_delay_from_error_body(self):
        retry = {'error': {'message': 'Quota exceeded PerMinute', 'status': 'RESOURCE_EXHAUSTED',
                           'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '300s'}]}}
        with patch.object(_Chat, 'body', retry):
            self.ask()
        until = min(v['until'] for v in smart_router._HEALTH.values())
        self.assertAlmostEqual(until - llm.time.monotonic(), 300, delta=3)   # eskiden hep 60 sn

    def test_gemini_daily_quota_ignores_short_retry_delay(self):
        daily = {'error': {'message': 'Quota exceeded PerDay', 'status': 'RESOURCE_EXHAUSTED',
                           'details': [{'retryDelay': '20s'}]}}
        with patch.object(_Chat, 'body', daily):
            self.ask()
        until = min(v['until'] for v in smart_router._HEALTH.values())
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
        self.assertEqual(post.call_count, 1)   # router dışı doğrudan çağrı da sınırlı modeli yeniden çağırmaz
        until = max(v[0] for v in llm._rate_limited.values())
        self.assertAlmostEqual(until - llm.time.monotonic(), 20, delta=2)


if __name__ == '__main__':
    unittest.main()
