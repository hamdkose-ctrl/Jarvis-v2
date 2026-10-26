import unittest

from modules import hooks


class ObserverHooksTests(unittest.TestCase):
    def setUp(self):
        hooks.clear()

    def tearDown(self):
        hooks.clear()

    def test_all_phase_two_hook_points_are_observable(self):
        seen = []
        for name in hooks.HOOK_NAMES:
            hooks.register(name, lambda event, name=name: seen.append((name, event["payload"])))
        hooks.emit("tool", {"tool": "read"}, owner="hamdi")
        self.assertEqual(seen, [("tool", {"tool": "read"})])
        self.assertEqual(set(hooks.HOOK_NAMES), {
            "agent", "tool", "model", "approval", "session", "sub_agent", "kanban",
        })

    def test_observer_cannot_change_execution_and_failure_isolated(self):
        payload = {"allowed": True}

        def observer(event):
            event["payload"]["allowed"] = False
            return {"decision": "deny"}

        def broken(_event):
            raise RuntimeError("hook kapalı")

        hooks.register("approval", observer)
        hooks.register("approval", broken)
        result = hooks.emit("approval", payload, owner="hamdi")
        self.assertEqual(payload, {"allowed": True})
        self.assertEqual(result, ["delivered", "failed:RuntimeError"])


if __name__ == "__main__":
    unittest.main()
