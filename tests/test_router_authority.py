"""Central router contract: adapter calls are the complete network-attempt budget."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import requests_state, smart_router as router


class RouterAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        for name, value in (('_STORE', Path(self.tmp.name)), ('_HEALTH', {})):
            item = patch.object(router, name, value); item.start(); self.addCleanup(item.stop)

    def test_schema_repair_and_fallback_share_two_network_attempts(self):
        request = router.ModelRequest(owner='alice', max_network_attempts=2,
                                      features=frozenset({'text', 'structured_output'}))
        specs = [router.ModelSpec('gemini', 'g1', features=frozenset({'text', 'structured_output'})),
                 router.ModelSpec('groq', 'g1', features=frozenset({'text', 'structured_output'})),
                 router.ModelSpec('ollama', 'local', features=frozenset({'text'}))]
        planned = router.RoutePlan(tuple(specs), (), 2)
        calls = []
        def adapter(spec):
            calls.append(spec.provider)
            return 'not-json' if len(calls) == 1 else '{"ok":true}'
        with patch.object(router, 'plan', return_value=planned):
            result = router.run_request(request, adapter, validator=lambda text: (_ for _ in ()).throw(ValueError()) if text == 'not-json' else None)
        self.assertEqual(result.text, '{"ok":true}')
        self.assertEqual(calls, ['gemini', 'groq'])

    def test_late_response_is_not_adopted(self):
        request = router.ModelRequest(owner='alice')
        planned = router.RoutePlan((router.ModelSpec('groq', 'm'),), (), 2)
        checks = iter((None, requests_state.LocalDeadline('expired')))
        def check():
            value = next(checks)
            if isinstance(value, BaseException):
                raise value
        with patch.object(router, 'plan', return_value=planned), patch.object(router.requests_state, 'check', side_effect=check):
            with self.assertRaises(requests_state.LocalDeadline):
                router.run_request(request, lambda _: 'late answer')
        self.assertFalse(any(t['state']=='completed' for t in router.status('alice')['traces']))


    def test_cancelled_request_rejects_adapter_invocation(self):
        from unittest.mock import Mock
        cancelled = Mock()
        cancelled.is_set.return_value = True
        request = router.ModelRequest(owner='alice', cancelled=cancelled)
        adapter = Mock(return_value='answer')
        planned = router.RoutePlan((router.ModelSpec('groq', 'm'),), (), 2)
        with patch.object(router, 'plan', return_value=planned):
            with self.assertRaises(requests_state.Cancelled):
                router.run_request(request, adapter)
        adapter.assert_not_called()

    def test_explicit_deadline_rejects_late_reply(self):
        request = router.ModelRequest(owner='alice', deadline=10.0)
        planned = router.RoutePlan((router.ModelSpec('groq', 'm'),), (), 2)
        checks = []
        def check(_):
            checks.append(True)
            if len(checks) >= 3:
                raise requests_state.LocalDeadline('expired')
        with patch.object(router, 'plan', return_value=planned), patch.object(router, '_check_request', side_effect=check):
            with self.assertRaises(requests_state.LocalDeadline):
                router.run_request(request, lambda spec: 'late reply')
        self.assertFalse(any(t['state']=='completed' for t in router.status('alice')['traces']))
        self.assertEqual(router._HEALTH, {})

    def test_cancel_or_deadline_inside_validator_stops_without_cooldown(self):
        request = router.ModelRequest(owner='alice')
        planned = router.RoutePlan((router.ModelSpec('groq', 'm'), router.ModelSpec('gemini', 'g')), (), 2)
        for exc in (requests_state.Cancelled('cancelled'), requests_state.LocalDeadline('expired')):
            calls = []
            def adapter(spec):
                calls.append(spec.provider)
                return 'answer'
            def validate(_):
                raise exc
            with self.subTest(error=type(exc).__name__), patch.object(router, 'plan', return_value=planned):
                with self.assertRaises(type(exc)):
                    router.run_request(request, adapter, validator=validate)
                self.assertEqual(calls, ['groq'])
                self.assertEqual(router._HEALTH, {})

    def test_missing_evidence_retains_reason_code(self):
        from modules.failure_policy import ProviderExhaustedError
        request = router.ModelRequest(owner='alice')
        skipped = ({'provider': 'groq', 'reason': 'missing evidence',
                    'reason_code': 'PROVIDER_FREE_TIER_EVIDENCE_MISSING'},)
        planned = router.RoutePlan((), skipped, 2)
        with patch.object(router, 'plan', return_value=planned):
            with self.assertRaises(ProviderExhaustedError) as caught:
                router.run_request(request, lambda _: 'unexpected')
        self.assertEqual(caught.exception.reason_code, 'PROVIDER_FREE_TIER_EVIDENCE_MISSING')
        self.assertEqual(caught.exception.recovery_class, 'user_action_required')

if __name__ == '__main__':
    unittest.main()
