import unittest
from unittest.mock import patch

from modules.gateway_hooks import GatewayEvent, GatewayHooks
from modules.shell_hooks import ShellHook, ShellHookResult


class GatewayHooksTests(unittest.TestCase):
    def test_publish_calls_only_matching_hooks_and_returns_machine_result(self):
        seen = []
        hooks = GatewayHooks()
        hooks.subscribe("goal.created", lambda event: seen.append(event.name))
        result = hooks.publish(GatewayEvent("goal.created", {"id": "g1"}, request_id="r1"))
        self.assertEqual(seen, ["goal.created"])
        self.assertEqual(result["event"], "goal.created")
        self.assertEqual(result["delivered"], 1)
        self.assertEqual(result["errors"], [])

    def test_invalid_hook_is_rejected_fail_closed(self):
        hooks = GatewayHooks()
        with self.assertRaises(ValueError):
            hooks.subscribe("goal.created", "not-callable")
        with self.assertRaises(ValueError):
            hooks.publish({"name": "goal.created"})

    def test_hook_exception_is_reported_without_dispatching_work(self):
        hooks = GatewayHooks()
        hooks.subscribe("goal.created", lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
        result = hooks.publish(GatewayEvent("goal.created", {}))
        self.assertEqual(result["delivered"], 0)
        self.assertEqual(result["errors"][0]["reason_code"], "HOOK_FAILED")


class ShellHookTests(unittest.TestCase):
    def test_stub_is_disabled_and_never_calls_subprocess(self):
        hook = ShellHook()
        with patch("subprocess.run") as run:
            result = hook.execute("echo unsafe")
        run.assert_not_called()
        self.assertIsInstance(result, ShellHookResult)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, "SHELL_EXECUTION_DISABLED")
        self.assertEqual(result.status, "blocked")

    def test_contract_rejects_ambiguous_input(self):
        hook = ShellHook()
        with self.assertRaises(ValueError):
            hook.execute("")
        with self.assertRaises(ValueError):
            hook.execute(["echo", "unsafe"])


if __name__ == "__main__":
    unittest.main()
