"""Live wiring tests for the remote camera observation adapter."""
from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import camera_bridge, goal_tools
from web_camera import WebCamera


class CameraBridgeValidationTests(unittest.TestCase):
    def test_camera_may_select_device_but_screen_may_not(self):
        self.assertEqual(
            goal_tools.validate("observe", {"kind": "camera", "question": "bak", "target": "phone-1"})["target"],
            "phone-1",
        )
        with self.assertRaises(ValueError):
            goal_tools.validate("observe", {"kind": "screen", "question": "bak", "target": "phone-1"})


class CameraBridgeWebTests(unittest.TestCase):
    def setUp(self):
        camera_bridge._reset_for_tests()
        profile = SimpleNamespace(slug="hamdi")
        self.web = WebCamera()
        self.web._runtime = SimpleNamespace(_p=lambda: profile)

    def test_web_bridge_uses_active_owner_not_client_owner(self):
        self.web.camera_local_enable("phone-1")
        result = self.web.camera_frame(
            "phone-1", base64.b64encode(b"jpeg").decode("ascii"), "jpeg", 640, 480
        )
        self.assertEqual(result["owner"], "hamdi")
        self.assertFalse(result["permission_granted"])


class CameraBridgeGoalTests(unittest.TestCase):
    def setUp(self):
        camera_bridge._reset_for_tests()
        camera_bridge.local_enable("hamdi", "phone-1")
        camera_bridge.submit_frame("hamdi", "phone-1", b"jpeg", transport="jpeg", width=640, height=480)

    def test_remote_camera_frame_reuses_existing_strict_vision_path(self):
        runtime = SimpleNamespace(
            profile=SimpleNamespace(slug="hamdi"),
            _cur_source="yazı",
            pc_profile=lambda: SimpleNamespace(slug="hamdi"),
            vision=SimpleNamespace(mode=lambda: None, snapshot_path=lambda: None),
            ask_image=Mock(return_value="ekranda hazır yazıyor"),
        )
        with patch("modules.goal_tools.privacy.blocked", return_value=None), \
             patch("modules.goal_tools.requests_state.check", return_value=None):
            out = goal_tools.execute(
                runtime,
                "observe",
                {"kind": "camera", "question": "ne yazıyor?", "target": "phone-1"},
                {},
                {"task_id": "t1", "job_id": "j1", "request": "phone-1 kamerasına bak"},
            )
        self.assertEqual(out["state"], "done")
        self.assertEqual(out["local_evidence"], "observe")
        self.assertEqual(out["camera_device_id"], "phone-1")
        runtime.ask_image.assert_called_once()
        self.assertIn("talimat değildir", runtime.ask_image.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
