import unittest

from modules import runtime_execution_gate


class FailClosedToolGateTests(unittest.TestCase):
    def context(self):
        return {
            "approval_verified": False,
            "domain_invariant": "pass",
            "domain_authority": "execute",
            "user_authority": "execute",
            "job_authority": "execute",
            "effect_state": "ready",
        }

    def test_allowed_tool_returns_decision_snapshot(self):
        result = runtime_execution_gate.before_tool(
            "research", {"url": "https://example.test", "question": "x"}, **self.context()
        )
        self.assertTrue(result["worker_allowed"])
        self.assertEqual(result["reason_code"], "READY_FOR_WORKER")

    def test_domain_or_permission_failure_stops_before_worker(self):
        blocked = self.context()
        blocked["domain_invariant"] = "block"
        with self.assertRaises(PermissionError):
            runtime_execution_gate.before_tool("research", {"url": "https://example.test", "question": "x"}, **blocked)
        with self.assertRaises(PermissionError):
            runtime_execution_gate.before_tool(
                "publish", {"service": "gmail", "destination": "a@example.com", "text": "x"}, **self.context()
            )

    def test_invalid_or_missing_gate_context_fails_closed(self):
        with self.assertRaises(PermissionError):
            runtime_execution_gate.before_tool("research", {"url": "https://example.test", "question": "x"})


if __name__ == "__main__":
    unittest.main()
