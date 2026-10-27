import unittest
from unittest.mock import patch


class CrossDeviceContinuityTests(unittest.TestCase):
    def test_same_owner_sees_same_open_work_across_devices_without_new_authority(self):
        from modules import continuity

        goal = {"id": "goal-7", "state": "running", "goal": "son haberleri araştır"}
        task = {"id": "task-3", "state": "incomplete", "updated": 123.0}
        with patch("modules.goal_executor.latest", return_value=goal), \
             patch("modules.goal_executor.is_open", return_value=True), \
             patch("modules.task_agents.recent", return_value=task):
            work_pc = continuity.snapshot("hamdi", device_id="work-pc", session_id="session-a")
            home_pc = continuity.snapshot("hamdi", device_id="home-pc", session_id="session-b")

        self.assertEqual(work_pc["goal"]["id"], "goal-7")
        self.assertEqual(home_pc["goal"]["id"], "goal-7")
        self.assertEqual(work_pc["task"]["id"], "task-3")
        self.assertEqual(home_pc["task"]["id"], "task-3")
        self.assertEqual(work_pc["device_id"], "work-pc")
        self.assertEqual(home_pc["session_id"], "session-b")
        self.assertEqual(work_pc["authority"], "core")
        self.assertFalse(work_pc["permission_granted"])

    def test_device_identity_is_metadata_not_owner_override(self):
        from modules import continuity

        with patch("modules.goal_executor.latest", return_value=None), \
             patch("modules.task_agents.recent", return_value=None):
            snap = continuity.snapshot("hamdi", device_id="ebru", session_id="phone-1")

        self.assertEqual(snap["owner"], "hamdi")
        self.assertEqual(snap["device_id"], "ebru")
        self.assertIsNone(snap["goal"])
        self.assertIsNone(snap["task"])
        self.assertFalse(snap["permission_granted"])


if __name__ == "__main__":
    unittest.main()
