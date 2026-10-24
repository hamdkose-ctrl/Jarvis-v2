"""goal_executor._record() provider/network failures must surface failure_policy's classified,
safe explanation instead of a raw exception string; other tool failures keep their own specific
message unchanged. No live provider or network call."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import failure_policy, goal_executor as goals, goal_tools
import test_goal_executor as fixture


class GoalFailurePolicyTests(unittest.TestCase):
    def case(self):
        case = fixture.GoalTests(); case.setUp(); self.addCleanup(case.doCleanups); return case

    def _failed_step(self, case, exc):
        """Run one 'note_add' action step whose bridge call raises exc; return its output dict.
        note_add is not in goal_tools.replay_safe's allowlist, so a failure here stops the run
        after a single tool step without needing further planner responses."""
        bridge = SimpleNamespace(note_add=Mock(side_effect=exc))
        case.responses(case.plan('Not ekle'), case.tool('action', {'action': 'note_add', 'params': {'text': 'New note'}}))
        with patch.object(goal_tools.app_actions, '_owned', return_value=nullcontext(bridge)):
            goals.run(case.runtime, 'New note diye not ekle')
        job = goals.latest('alice')
        step = next(s for s in job['steps'] if s['tool'] == 'action')
        self.assertEqual(step['state'], 'failed')
        return job['outputs'][step['id']]

    def test_rate_limit_error_is_classified_and_does_not_leak_raw_text(self):
        case = self.case()
        raw = RuntimeError('HTTP 429 quota exceeded for key sk-abcdef123 on model gemini-x')
        output = self._failed_step(case, raw)
        self.assertEqual(output['state'], 'failed')
        self.assertEqual(output['text'], failure_policy.explain(raw))
        self.assertNotIn('sk-abcdef123', output['text'])
        self.assertEqual(failure_policy.classify(raw), failure_policy.RATE_LIMIT)

    def test_dns_failure_is_classified_and_does_not_leak_raw_text(self):
        case = self.case()
        raw = OSError('Name or service not known')
        output = self._failed_step(case, raw)
        self.assertEqual(output['text'], failure_policy.explain(raw))
        self.assertEqual(failure_policy.classify(raw), failure_policy.DNS)

    def test_ollama_connection_refused_is_classified_and_does_not_leak_raw_text(self):
        case = self.case()
        raw = ConnectionRefusedError(111, 'Connection refused')
        output = self._failed_step(case, raw)
        self.assertEqual(output['text'], failure_policy.explain(raw))
        self.assertEqual(failure_policy.classify(raw), failure_policy.NETWORK)

    def test_auth_failure_is_classified_and_does_not_leak_raw_text(self):
        case = self.case()
        raw = RuntimeError('invalid_grant: api_key revoked for user abc@example.com')
        output = self._failed_step(case, raw)
        self.assertEqual(output['text'], failure_policy.explain(raw))
        self.assertEqual(failure_policy.classify(raw), failure_policy.AUTH)
        self.assertNotIn('abc@example.com', output['text'])

    def test_non_provider_tool_error_keeps_its_own_specific_message(self):
        case = self.case()
        raw = ValueError('Not metni boş olamaz')
        output = self._failed_step(case, raw)
        self.assertEqual(output['state'], 'failed')
        self.assertIn('Not metni boş olamaz', output['text'])
        self.assertNotEqual(output['text'], failure_policy.explain(raw))


if __name__ == '__main__':
    unittest.main()
