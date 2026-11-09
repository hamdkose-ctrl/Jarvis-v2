"""Central router contract: adapter calls are the complete network-attempt budget."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import requests_state, smart_router as router


class RouterAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        for name, value in (('_STORE', Path(self.tmp.name)), ('_HEALTH', {}), ('_LAST', {})):
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
        self.assertEqual(router._LAST, {})


if __name__ == '__main__':
    unittest.main()
