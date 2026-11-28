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
            "agent", "tool", "model", "approval", "session", "sub_agent", "kanban", "gateway",
        })

    def test_ownerless_event_reaches_global_observer_once(self):
        seen = []
        hooks.register('tool', seen.append)
        hooks.emit('tool', {'tool': 'read'})
        self.assertEqual(len(seen), 1)

    def test_ownerless_event_skips_owner_lists(self):
        seen = []
        hooks.register('tool', lambda event: seen.append('global'))
        hooks.register('tool', lambda event: seen.append('hamdi'), owner='hamdi')
        hooks.emit('tool', {'tool': 'read'})
        self.assertEqual(seen, ['global'])
        hooks.emit('tool', {'tool': 'read'}, owner='hamdi')
        self.assertEqual(seen, ['global', 'global', 'hamdi'])

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
