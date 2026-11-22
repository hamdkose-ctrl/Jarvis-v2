"""Yavaş sağlayıcı denemesi: sınır aşılırsa sıradaki sağlayıcı denenir.

Ölçüm (22 Kasım, 89 konuşma çağrısı): medyan 1,05 sn ama p90 7,0 sn, en kötü
14,8 sn — ve o çağrı yalnız 49 token üretmiş. Yani zaman sağlayıcı kuyruğunda
geçiyor. Bu yüzden tek deneme sınırlanır; İSTEK bütçesi (LocalDeadline) aynen
korunur, tur iptal edilmez.
"""
import time
import unittest
from unittest.mock import patch

from modules import requests_state, smart_router


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


class AttemptTimeoutTests(unittest.TestCase):
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

        with _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini', 'groq')):
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

        with _ayar(0.5), patch.object(smart_router, 'plan', return_value=_plan('gemini')):
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


class TransportTimeoutTests(unittest.TestCase):
    def test_socket_read_timeout_is_capped_by_the_attempt_budget(self):
        from modules import llm
        with requests_state.budget(3):
            connect, read = llm.transport_timeouts(5, 45)
        self.assertLessEqual(read, 3.1)


if __name__ == '__main__':
    unittest.main()
