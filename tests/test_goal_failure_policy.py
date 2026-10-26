"""Provider/model failures must surface safe structured outcomes in goal runtime.

Test-first contract: provider/network failures get stable reason_code + recovery_class;
non-provider tool errors keep their specific message. No live provider/network call.
"""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import failure_policy, goal_executor as goals, goal_tools, llm, smart_router
import test_goal_executor as fixture


class GoalFailurePolicyTests(unittest.TestCase):
    def case(self):
        case = fixture.GoalTests(); case.setUp(); self.addCleanup(case.doCleanups); return case

    def _failed_step(self, case, exc):
        """Run one action step whose bridge call raises exc; return job and output."""
        bridge = SimpleNamespace(note_add=Mock(side_effect=exc))
        case.responses(case.plan('Not ekle'), case.tool('action', {'action': 'note_add', 'params': {'text': 'New note'}}))
        with patch.object(goal_tools.app_actions, '_owned', return_value=nullcontext(bridge)):
            goals.run(case.runtime, 'New note diye not ekle')
        job = goals.latest('alice')
        step = next(s for s in job['steps'] if s['tool'] == 'action')
        self.assertEqual(step['state'], 'failed')
        return job, job['outputs'][step['id']]

    def assert_provider_outcome(self, exc, reason_code, recovery_class):
        case = self.case()
        job, output = self._failed_step(case, exc)
        self.assertEqual(output['state'], 'failed')
        self.assertEqual(output['reason_code'], reason_code)
        self.assertEqual(output['recovery_class'], recovery_class)
        self.assertNotEqual(job['state'], 'done')
        return output

    def test_rate_limit_error_has_structured_reason_and_safe_text(self):
        raw = RuntimeError('HTTP 429 quota exceeded for key sk-abcdef123 on model gemini-x')
        output = self.assert_provider_outcome(raw, 'PROVIDER_RATE_LIMIT', 'fallback_possible')
        self.assertEqual(output['text'], failure_policy.explain(raw))
        self.assertNotIn('sk-abcdef123', output['text'])
        self.assertEqual(failure_policy.classify(raw), failure_policy.RATE_LIMIT)

    def test_auth_failure_has_structured_reason_and_no_secret_or_raw_body(self):
        raw = RuntimeError('HTTP 401 invalid_grant api_key=sk-SECRET raw-body user abc@example.com')
        output = self.assert_provider_outcome(raw, 'PROVIDER_AUTH', 'fallback_possible')
        self.assertEqual(output['text'], failure_policy.explain(raw))
        self.assertNotIn('sk-SECRET', output['text'])
        self.assertNotIn('raw-body', output['text'])
        self.assertNotIn('abc@example.com', output['text'])

    def test_dns_network_and_timeout_have_distinct_reason_codes(self):
        rows = [
            (OSError('Name or service not known'), 'PROVIDER_DNS'),
            (ConnectionRefusedError(111, 'Connection refused PRIVATE'), 'PROVIDER_NETWORK'),
            (TimeoutError('PRIVATE timed out'), 'PROVIDER_TIMEOUT'),
        ]
        for exc, reason in rows:
            with self.subTest(reason=reason):
                output = self.assert_provider_outcome(exc, reason, 'retryable')
                self.assertNotIn('PRIVATE', output['text'])

    def test_provider_down_has_structured_reason(self):
        class Down(RuntimeError):
            status_code = 503
        output = self.assert_provider_outcome(Down('PRIVATE service unavailable'), 'PROVIDER_DOWN', 'fallback_possible')
        self.assertNotIn('PRIVATE', output['text'])

    def test_ollama_missing_is_local_model_and_user_action(self):
        raw = llm.LocalModelError('Ollama kurulu değil; secret-path=C:/PRIVATE')
        output = self.assert_provider_outcome(raw, 'PROVIDER_LOCAL_MODEL', 'user_action_required')
        self.assertIn('Ollama', output['text'])
        self.assertNotIn('PRIVATE', output['text'])
        self.assertNotIn('secret-path', output['text'])

    def test_missing_key_is_not_real_provider_auth_failure(self):
        skipped = [
            {'provider': 'gemini', 'reason': 'Bu kullanıcı için API anahtarı eksik', 'seconds': 0},
            {'provider': 'groq', 'reason': 'Bu kullanıcı için API anahtarı eksik', 'seconds': 0},
        ]
        with patch.object(smart_router, 'candidates', return_value=[]), \
             patch.object(smart_router, 'selection', return_value={'candidates': [], 'skipped': skipped}), \
             patch.object(smart_router, '_free_emergency', return_value=False):
            with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
                smart_router.run('alice', 'python', Mock(side_effect=AssertionError('no call')))
        self.assertEqual(caught.exception.reason_code, 'PROVIDER_CONFIGURATION_REQUIRED')
        self.assertEqual(caught.exception.recovery_class, 'user_action_required')
        self.assertNotEqual(caught.exception.reason_code, 'PROVIDER_AUTH')

    def test_all_providers_exhausted_has_stable_structured_failure(self):
        errors = [RuntimeError('429 quota PRIVATE'), TimeoutError('PRIVATE'), ConnectionError('PRIVATE')]
        with patch.object(smart_router, 'candidates', return_value=['groq', 'gemini', 'ollama']), \
             patch.object(smart_router, 'selection', return_value={'candidates': ['groq', 'gemini', 'ollama'], 'skipped': []}), \
             patch.object(smart_router, '_free_emergency', return_value=False):
            with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
                smart_router.run('alice', 'python', Mock(side_effect=errors))
        exc = caught.exception
        self.assertEqual(exc.reason_code, 'PROVIDER_POOL_EXHAUSTED')
        self.assertEqual(exc.recovery_class, 'fail_closed')
        self.assertEqual(failure_policy.classify(exc), failure_policy.PROVIDER_EXHAUSTED)
        self.assertNotIn('PRIVATE', failure_policy.explain(exc))

    def test_non_provider_tool_error_keeps_its_own_specific_message(self):
        case = self.case()
        raw = ValueError('Not metni boş olamaz')
        job, output = self._failed_step(case, raw)
        self.assertEqual(output['state'], 'failed')
        self.assertIn('Not metni boş olamaz', output['text'])
        self.assertNotIn('reason_code', output)
        self.assertNotIn('recovery_class', output)
        self.assertNotEqual(output['text'], failure_policy.explain(raw))
        self.assertNotEqual(job['state'], 'done')


if __name__ == '__main__':
    unittest.main()
