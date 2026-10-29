import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests
from modules import failure_policy, hoca, llm, smart_router


class ProviderHocaDiagnosticsTests(unittest.TestCase):
    def test_read_timeout_is_not_reported_as_missing_local_server(self):
        with patch.object(llm, '_cfg', return_value={'backend': 'ollama', 'url': 'http://localhost:11434'}), \
             patch.object(llm, '_ollama_effective_model', return_value='qwen2.5:3b'), \
             patch.object(llm.requests, 'post', side_effect=requests.ReadTimeout('private')), \
             patch.object(llm.usage_meter, 'record'):
            with self.assertRaises(llm.LocalModelError) as caught:
                llm._ollama([{'role': 'user', 'content': 'test'}], '', 10)
        self.assertNotEqual(str(caught.exception), llm.local_hint())
        self.assertIn('zaman aşımı', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))

    def test_router_trace_preserves_wrapped_timeout_type(self):
        cause = requests.ReadTimeout('private')
        wrapped = llm.LocalModelError(llm.local_hint())
        wrapped.__cause__ = cause
        with patch.object(smart_router, 'selection', return_value={'candidates': ['ollama'], 'skipped': []}), \
             patch.object(smart_router, '_free_emergency', return_value=False), \
             patch.object(smart_router, '_HEALTH', {}), patch.object(smart_router, '_LAST', {}), \
             patch.object(llm, 'note_route') as note:
            with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
                smart_router.run('diagnostic-test', 'test', lambda _: (_ for _ in ()).throw(wrapped))
            trace = smart_router._LAST['diagnostic-test']['attempts'][0]
        self.assertEqual(trace['error'], 'ReadTimeout')
        self.assertNotEqual(trace.get('hint'), 'ollama_missing')
        self.assertIn('zaman aşımı', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))
        self.assertIn('zaman aşımı', note.call_args.args[0])

    def test_connection_refusal_remains_unavailable_without_raw_transport_message(self):
        wrapped = llm.LocalModelError(llm.local_hint())
        wrapped.__cause__ = requests.ConnectionError('private-secret')
        with patch.object(smart_router, 'selection', return_value={'candidates': ['ollama'], 'skipped': []}), \
             patch.object(smart_router, '_free_emergency', return_value=False), \
             patch.object(smart_router, '_HEALTH', {}), patch.object(smart_router, '_LAST', {}), \
             patch.object(llm, 'note_route'):
            with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
                smart_router.run('diagnostic-test', 'test', lambda _: (_ for _ in ()).throw(wrapped))
            trace = smart_router._LAST['diagnostic-test']['attempts'][0]
        self.assertEqual(trace['error'], 'ConnectionError')
        self.assertEqual(trace.get('hint'), 'ollama_missing')
        self.assertNotIn('private-secret', str(caught.exception))

    def test_hoca_preserves_safe_exhausted_reason_and_metadata_without_saving(self):
        profile = SimpleNamespace(data={}, save=lambda: self.fail('failed lesson saved'))
        error = failure_policy.ProviderExhaustedError(
            'ollama: zaman aşımı. https://example.test/path?key=private-secret',
            reason_code='PROVIDER_FREE_TIER_MISSING', recovery_class='user_action_required')
        for call in (lambda: hoca.start(profile, 'fotosentez'),
                     lambda: hoca._ask('test', '', 10, 'test', 'Kontrol sorusu')):
            with self.subTest(call=call), patch.object(llm, 'ask', side_effect=error):
                with self.assertRaises(hoca.HocaError) as caught:
                    call()
                self.assertIn('zaman aşımı', str(caught.exception))
                self.assertNotIn('private-secret', str(caught.exception))
                self.assertNotIn('Biraz sonra tekrar dene', str(caught.exception))
                self.assertEqual(caught.exception.reason_code, error.reason_code)
                self.assertEqual(caught.exception.recovery_class, error.recovery_class)
        self.assertFalse(profile.data)

    def test_unknown_hoca_failure_does_not_expose_arbitrary_error(self):
        profile = SimpleNamespace(data={}, save=lambda: None)
        with patch.object(llm, 'ask', side_effect=RuntimeError('private-secret')):
            with self.assertRaises(hoca.HocaError) as caught:
                hoca.start(profile, 'test')
        self.assertNotIn('private-secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
