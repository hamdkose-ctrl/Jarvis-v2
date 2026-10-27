import importlib.util
import unittest
from unittest.mock import patch

from modules import hooks
from modules.shell_hooks import ShellHook, ShellHookResult


class GatewayHooksTests(unittest.TestCase):
    def setUp(self):
        hooks.clear()

    def tearDown(self):
        hooks.clear()

    def test_gateway_observation_uses_single_canonical_registry(self):
        seen = []
        payload = {"event": "goal.created", "request_id": "r1", "payload": {"id": "g1"}}
        hooks.register("gateway", lambda event: seen.append(event))

        result = hooks.emit("gateway", payload, owner="alice")

        self.assertEqual(result, ["delivered"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["name"], "gateway")
        self.assertEqual(seen[0]["owner"], "alice")
        self.assertEqual(seen[0]["payload"], payload)

    def test_gateway_observer_result_cannot_change_execution_authority(self):
        payload = {"allowed": True, "event": "tool.before"}

        def observer(event):
            event["payload"]["allowed"] = False
            return {"decision": "deny"}

        hooks.register("gateway", observer)
        result = hooks.emit("gateway", payload, owner="alice")

        self.assertEqual(result, ["delivered"])
        self.assertEqual(payload, {"allowed": True, "event": "tool.before"})

    def test_gateway_observer_failure_is_isolated(self):
        hooks.register(
            "gateway",
            lambda _event: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        result = hooks.emit("gateway", {"event": "goal.created"}, owner="alice")

        self.assertEqual(result, ["failed:RuntimeError"])

    def test_no_second_gateway_hook_implementation_exists(self):
        self.assertIsNone(importlib.util.find_spec("modules.gateway_hooks"))


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
