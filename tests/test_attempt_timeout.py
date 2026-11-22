"""Yavaş sağlayıcı denemesi: sınır aşılırsa sıradaki sağlayıcı denenir.

Ölçüm (22 Kasım, 89 konuşma çağrısı): medyan 1,05 sn ama p90 7,0 sn, en kötü
14,8 sn — ve o çağrı yalnız 49 token üretmiş. Yani zaman sağlayıcı kuyruğunda
geçiyor. Bu yüzden tek deneme sınırlanır; İSTEK bütçesi (LocalDeadline) aynen
korunur, tur iptal edilmez.
"""
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from modules import requests_state, smart_router


@contextmanager
def _temiz_butce(saniye=30.0):
    """Testin kendi bütçesi: tam takımda kalan bir bütçe/iptal işareti sonucu değiştirmesin.

    Canlı kanıt (tam doğrulama, 22 Kasım 2026): tek başına geçen test, 7130 testlik
    turda düştü çünkü önceki testten kalan kısa bütçe "zaten sıkı, bozmam" yolunu açtı.
    """
    deadline = requests_state._budget_deadline.set(None)
    cancel = requests_state._budget_cancel.set(None)
    try:
        with requests_state.budget(saniye):
            yield
    finally:
        requests_state._budget_cancel.reset(cancel)
        requests_state._budget_deadline.reset(deadline)


def _ayar(saniye):
    return patch('config.load_settings', lambda: {'attempt_timeout_s': saniye})


def _request(**kwargs):
    params = dict(owner='hamdi', profile='conversation', data_scope='conversation',
                  work_class='interactive', max_output_tokens=200)
    params.update(kwargs)
    return smart_router.ModelRequest(**params)


def _plan(*providers):
    return smart_router.RoutePlan(
        tuple(smart_router.ModelSpec(p, 'model-' + p) for p in providers), (), 2)


class _TemizButce(unittest.TestCase):
    """Her test kendi bütçesiyle başlar: tam takımda sızmış bütçe sonucu değiştirmez."""

    def setUp(self):
        self._butce = _temiz_butce()
        self._butce.__enter__()

    def tearDown(self):
        self._butce.__exit__(None, None, None)


class AttemptTimeoutTests(_TemizButce):
    def test_slow_first_provider_is_abandoned_for_the_next_one(self):
        cagrilar = []

        def transport(spec):
            cagrilar.append(spec.provider)
            if spec.provider == 'gemini':
                # Gerçek taşıma gibi: okuma sınırı bütçeden gelir ve her adımda
                # bütçe denetlenir (llm.transport_timeouts + requests_state.check).
                for _ in range(40):
                    time.sleep(0.05)
                    requests_state.check()
            return 'yanıt'

        # Yedek adayın "hazır" görünmesi ortam anahtarlarına bağlı olmamalı: tam takımda
        # başka testlerin bıraktığı anahtar durumu testi sessizce tek sağlayıcıya düşürüyordu.
        with _temiz_butce(), _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini', 'groq')),                 patch.object(smart_router, '_ready_key_configured', lambda owner, provider: True),                 patch.object(smart_router, '_current_admission', lambda *a, **k: True),                 patch.object(smart_router, '_health_wait', lambda *a, **k: 0),                 patch('modules.usage_meter.observed_exhaustion', lambda *a, **k: None):
            result = smart_router._run_request(_request(), transport)
        self.assertEqual(result.text, 'yanıt')
        self.assertEqual(cagrilar, ['gemini', 'groq'])

    def test_no_alternative_means_no_abort(self):
        cagrilar = []

        def transport(spec):
            cagrilar.append(spec.provider)
            for _ in range(16):
                time.sleep(0.05)
                requests_state.check()
            return 'yavaş ama tek'

        with _temiz_butce(), _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini')):
            result = smart_router._run_request(_request(), transport)
        self.assertEqual(result.text, 'yavaş ama tek')
        self.assertEqual(cagrilar, ['gemini'])

    def test_setting_zero_keeps_the_old_behaviour(self):
        cagrilar = []

        def transport(spec):
            cagrilar.append(spec.provider)
            for _ in range(16):
                time.sleep(0.05)
                requests_state.check()
            return 'beklendi'

        with _ayar(0), patch.object(smart_router, 'plan', return_value=_plan('gemini', 'groq')):
            result = smart_router._run_request(_request(), transport)
        self.assertEqual(result.text, 'beklendi')
        self.assertEqual(cagrilar, ['gemini'])

    def test_non_interactive_work_is_not_capped(self):
        cagrilar = []

        def transport(spec):
            cagrilar.append(spec.provider)
            for _ in range(16):
                time.sleep(0.05)
                requests_state.check()
            return 'uzun iş'

        with _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini', 'groq')):
            result = smart_router._run_request(_request(work_class='background'), transport)
        self.assertEqual(result.text, 'uzun iş')
        self.assertEqual(cagrilar, ['gemini'])

    def test_attempt_timeout_does_not_punish_the_provider(self):
        def transport(spec):
            if spec.provider == 'gemini':
                for _ in range(40):
                    time.sleep(0.05)
                    requests_state.check()
                return 'geç'
            return 'hızlı'

        with _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini', 'groq')):
            smart_router._run_request(_request(), transport)
        with smart_router._LOCK:
            anahtarlar = list(smart_router._HEALTH)
        self.assertFalse([k for k in anahtarlar if 'gemini' in str(k) and 'attempt' in str(k)])


class TransportTimeoutTests(_TemizButce):
    def test_socket_read_timeout_is_capped_by_the_attempt_budget(self):
        from modules import llm
        with requests_state.budget(3):
            connect, read = llm.transport_timeouts(5, 45)
        self.assertLessEqual(read, 3.1)


if __name__ == '__main__':
    unittest.main()


class FallbackHealthTests(_TemizButce):
    """Sınır yalnız yedek SAĞLIKLI ise uygulanır (canlı hata 22 Kasım 13:31)."""

    def _kos(self, transport, *, health=None, exhausted=None):
        with _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini', 'groq')), \
                patch.object(smart_router, '_ready_key_configured', lambda owner, provider: True),                 patch.object(smart_router, '_current_admission', lambda *a, **k: True), \
                patch.object(smart_router, '_health_wait', lambda *a, **k: health), \
                patch('modules.usage_meter.observed_exhaustion', lambda *a, **k: exhausted):
            return smart_router._run_request(_request(), transport)

    def test_no_abort_when_the_fallback_is_in_cooldown(self):
        cagrilar = []

        def transport(spec):
            cagrilar.append(spec.provider)
            for _ in range(16):
                time.sleep(0.05)
                requests_state.check()
            return 'yavaş ama geldi'

        result = self._kos(transport, health=42)
        self.assertEqual(result.text, 'yavaş ama geldi')
        self.assertEqual(cagrilar, ['gemini'])

    def test_no_abort_when_the_fallback_is_quota_exhausted(self):
        cagrilar = []

        def transport(spec):
            cagrilar.append(spec.provider)
            for _ in range(16):
                time.sleep(0.05)
                requests_state.check()
            return 'kotasız yedek yok'

        result = self._kos(transport, health=None, exhausted={'until': time.time() + 60})
        self.assertEqual(result.text, 'kotasız yedek yok')
        self.assertEqual(cagrilar, ['gemini'])

    def test_abort_happens_when_the_fallback_is_healthy(self):
        cagrilar = []

        def transport(spec):
            cagrilar.append(spec.provider)
            if spec.provider == 'gemini':
                for _ in range(40):
                    time.sleep(0.05)
                    requests_state.check()
            return 'hızlı yedek'

        result = self._kos(transport, health=None, exhausted=None)
        self.assertEqual(result.text, 'hızlı yedek')
        self.assertEqual(cagrilar, ['gemini', 'groq'])

    def test_sdk_specific_error_after_the_deadline_is_not_a_provider_fault(self):
        def transport(spec):
            if spec.provider == 'gemini':
                for _ in range(40):
                    time.sleep(0.05)
                    requests_state.check()
                raise ValueError('sdk-özel tip')
            return 'yedek'

        with _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini', 'groq')):
            result = smart_router._run_request(_request(), transport)
        self.assertEqual(result.text, 'yedek')
