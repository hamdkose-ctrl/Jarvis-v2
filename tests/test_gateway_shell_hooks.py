import unittest

from modules import gateway_hooks


class GatewayShellHookTests(unittest.TestCase):
    def test_gateway_event_is_observable(self):
        seen = []
        result = gateway_hooks.emit("request.accepted", {"rid": "r1"}, [lambda event: seen.append(event)])
        self.assertEqual(result, ["delivered"])
        self.assertEqual(seen[0]["name"], "request.accepted")

    def test_shell_hook_is_fail_closed_without_sandbox(self):
        result = gateway_hooks.shell_before("echo merhaba")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason_code"], "SANDBOX_REQUIRED")

    def test_unknown_gateway_event_is_rejected(self):
        with self.assertRaises(ValueError):
            gateway_hooks.emit("shell.execute", {}, [])


if __name__ == "__main__":
    unittest.main()
