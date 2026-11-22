import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from modules import cloudflare_chat, llm, provider_privacy, router_quota, smart_router, usage_meter


class ReadyProviderRoutingTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(smart_router, '_STORE', Path(directory)))
        self.enterContext(patch.object(smart_router, '_HEALTH', {}))
        self.enterContext(patch.object(smart_router.privacy, 'mode', return_value='normal'))
        self.enterContext(patch.object(llm, 'user_key', return_value='gemini-test-key'))
        self.enterContext(patch.object(llm, 'user_groq_key', return_value='groq-test-key'))
        self.enterContext(patch.object(cloudflare_chat, 'configured', return_value=True))
        self.enterContext(patch.object(llm, '_ollama_effective_model', return_value='local-test'))

    def request(self, **kwargs):
        return smart_router.ModelRequest(owner='alice', profile='conversation', **kwargs)

    def ready(self, provider):
        return smart_router.ready_status('alice')['ready_connections'][provider]

    def test_ready_route_uses_keys_and_consent_without_local_billing_or_quota(self):
        self.assertEqual(smart_router.settings('alice'), {'gemini_scopes': []})
        self.assertEqual(smart_router.candidates('alice', 'chat'), ['groq', 'cloudflare', 'ollama'])
        smart_router.configure('alice', gemini_scopes=['conversation'])
        self.assertEqual(smart_router.candidates('alice', 'chat'), ['gemini', 'groq', 'cloudflare', 'ollama'])
        with patch.object(router_quota, 'reserve', side_effect=AssertionError('local quota')), \
             patch.object(router_quota, 'admission', side_effect=AssertionError('local semaphore')):
            result = smart_router.run_request(self.request(), lambda spec: spec.provider)
        self.assertEqual(result.text, 'gemini')
        self.assertEqual(self.ready('gemini')['state'], 'ok')

    def test_ready_connections_work_with_fresh_evidence(self):
        # P0-2: kanıt tazeyken (bugün) üç hazır bağlantı da çalışır.
        with patch('time.time', return_value=1_796_083_200), \
             patch.object(llm, 'active_model', return_value='gemini-3.5-flash-lite'), \
             patch.object(llm, 'dispatch', return_value='OK') as send:
            for provider in ('gemini', 'groq', 'cloudflare'):
                with self.subTest(provider=provider):
                    self.assertTrue(smart_router.check_ready_connection('alice', provider)['ok'])
                    self.assertEqual(send.call_args.args[1].provider, provider)
                    self.assertEqual(self.ready(provider)['state'], 'ok')
            self.assertEqual(send.call_count, 3)

            request = smart_router.ModelRequest(owner='alice', profile='vision',
                data_scope='selected_content', features=frozenset({'vision'}))
            self.assertFalse(smart_router.plan(request).candidates)
            smart_router.configure('alice', gemini_scopes=['selected_content'])
            self.assertEqual([spec.provider for spec in smart_router.plan(request).candidates], ['gemini'])

    def test_expired_privacy_evidence_closes_cloud_routes(self):
        """Kanıt süresi dolunca bulut rotaları kapanır; sessizce çalışmaya devam etmez."""
        later = max(facts['expires_at'] for facts in provider_privacy.PROVIDER_BUNDLE.values()) + 60
        with patch('time.time', return_value=later):
            for provider in ('gemini', 'groq', 'cloudflare'):
                with self.subTest(provider=provider):
                    self.assertFalse(provider_privacy.privacy_gate(provider, 'PUBLIC_RESEARCH')['ok'])
                    self.assertNotEqual(self.ready(provider)['state'], 'ok')
            self.assertEqual(smart_router.candidates('alice', 'chat'), ['ollama'])

    def test_provider_quota_is_visible_and_fallback_keeps_the_answering_model(self):
        smart_router.configure('alice', gemini_scopes=['conversation'])

        def respond(spec):
            if spec.provider == 'gemini':
                raise requests.HTTPError('HTTP 429 daily quota exceeded')
            return 'Groq answered'

        result = smart_router.run_request(self.request(), respond)
        self.assertEqual(result.model.provider, 'groq')
        self.assertEqual(self.ready('gemini')['state'], 'quota')
        self.assertIn('kotanın dolduğunu', self.ready('gemini')['message'])
        state = smart_router.ready_status('alice')
        self.assertEqual(state['last_reply'], {'provider': 'groq', 'model': result.model.model})
        self.assertNotIn('gemini-test-key', str(state))

    def test_cloud_reply_does_not_wait_for_local_model_discovery(self):
        smart_router.configure('alice', gemini_scopes=['conversation'])
        with patch.object(llm, '_ollama_effective_model') as discover:
            self.assertEqual(smart_router.run_request(self.request(), lambda spec: spec.provider).text, 'gemini')
        discover.assert_not_called()

    def test_local_model_is_discovered_only_after_the_only_cloud_attempt_fails(self):
        events = []

        def discover(*_args, **_kwargs):
            events.append('discover')
            return 'local-test'

        def respond(spec):
            events.append(spec.provider)
            if spec.provider == 'groq':
                raise requests.HTTPError('HTTP 429 daily quota exceeded')
            return 'OK'

        with patch.object(cloudflare_chat, 'configured', return_value=False), \
             patch.object(llm, '_ollama_effective_model', side_effect=discover):
            self.assertEqual(smart_router.run_request(self.request(), respond).model.provider, 'ollama')
        self.assertEqual(events[0], 'groq')
        self.assertIn('discover', events[1:-1])
        self.assertEqual(events[-1], 'ollama')

    def test_connection_probe_only_calls_requested_provider_with_no_chat_content(self):
        self.assertEqual(self.ready('cloudflare')['state'], 'unchecked')
        with patch.object(llm, 'dispatch', return_value='OK') as send:
            response = smart_router.check_ready_connection('alice', 'cloudflare')
        self.assertTrue(response['ok'])
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1].provider, 'cloudflare')
        self.assertEqual(send.call_args.args[2:], ('Reply with OK.', ''))
        self.assertEqual(response['status']['ready_connections']['cloudflare']['state'], 'ok')
        self.assertIsNone(response['status']['last_reply'])

        with patch.object(llm, 'dispatch', side_effect=requests.HTTPError('401 test key')) as send:
            response = smart_router.check_ready_connection('alice', 'groq')
        send.assert_called_once()
        self.assertFalse(response['ok'])
        self.assertEqual(response['status']['ready_connections']['groq']['state'], 'error')

    def test_cloudflare_http_429_is_reported_without_a_guess_at_the_daily_limit(self):
        response = Mock(status_code=429, text='Too many requests')
        with patch.object(cloudflare_chat, 'user_cloudflare_account', return_value='a' * 32), \
             patch.object(cloudflare_chat, 'user_cloudflare_token', return_value='cf-test-key'), \
             patch.object(requests, 'post', return_value=response) as send:
            result = smart_router.check_ready_connection('alice', 'cloudflare')
        send.assert_called_once()
        self.assertFalse(result['ok'])
        row = result['status']['ready_connections']['cloudflare']
        self.assertEqual(row['state'], 'quota')
        self.assertIn('hız sınırı', row['message'])
        self.assertNotIn('kotanın dolduğunu', row['message'])

    def test_key_rotation_drops_previous_connection_status(self):
        with patch.object(llm, 'dispatch', return_value='OK'):
            self.assertTrue(smart_router.check_ready_connection('alice', 'groq')['ok'])
        with patch.object(llm, 'user_groq_key', return_value='rotated-key'):
            self.assertEqual(self.ready('groq')['state'], 'unchecked')

    def test_provider_reset_is_bound_to_the_key_that_received_it(self):
        provider = 'groq'
        model = llm.groq_model()
        with tempfile.TemporaryDirectory() as path, patch.object(usage_meter, '_dir', return_value=Path(path)):
            usage_meter.observe_limits(provider, model, {
                'x-ratelimit-remaining-requests': '0',
                'x-ratelimit-reset-requests': '60s',
            }, owner='alice', credential=smart_router._connection_fingerprint('alice', provider))
            self.assertEqual(self.ready(provider)['state'], 'quota')
            self.assertNotIn(provider, smart_router.candidates('alice', 'chat'))
            with patch.object(llm, 'user_groq_key', return_value='rotated-key'):
                self.assertEqual(self.ready(provider)['state'], 'unchecked')
                self.assertIn(provider, smart_router.candidates('alice', 'chat'))

    def test_private_mode_does_not_send_probe(self):
        with patch.object(smart_router.privacy, 'mode', return_value='yerel'), patch.object(llm, 'dispatch') as send:
            result = smart_router.check_ready_connection('alice', 'gemini')
        send.assert_not_called()
        self.assertFalse(result['ok'])
        self.assertEqual(result['status']['ready_connections']['gemini']['state'], 'disabled')

    def test_untrusted_legacy_state_cannot_grant_gemini_data_permission(self):
        smart_router._save_state('alice', {
            'free_tier_evidence': {'gemini': {'trains_on_data': False}},
            'gemini_scopes': ['typo', None],
            'application_limits': {'daily_requests': 0},
        })
        self.assertEqual(smart_router.settings('alice'), {'gemini_scopes': []})
        self.assertNotIn('gemini', smart_router.candidates('alice', 'chat'))
        self.assertIn('gemini', smart_router.candidates('alice', 'analysis', provider_privacy.ROUTE_PUBLIC_RESEARCH))
