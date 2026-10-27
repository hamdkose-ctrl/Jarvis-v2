"""Live wiring tests for the remote camera device adapter.

This PR wires the device bridge into the existing authenticated WebChat surface.
Vision/goal observe wiring is intentionally left for the next step.
"""
from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace

from modules import camera_bridge
from web_chat import WebChat


class CameraBridgeWebTests(unittest.TestCase):
    def setUp(self):
        camera_bridge._reset_for_tests()
        profile = SimpleNamespace(slug="hamdi")
        self.web = WebChat()
        self.web._runtime = SimpleNamespace(_p=lambda: profile)

    def test_web_bridge_uses_active_owner_not_client_owner(self):
        self.web.camera_local_enable("phone-1")
        result = self.web.camera_frame(
            "phone-1", base64.b64encode(b"jpeg").decode("ascii"), "jpeg", 640, 480
        )
        self.assertEqual(result["owner"], "hamdi")
        self.assertFalse(result["permission_granted"])

    def test_web_observation_is_read_only_metadata(self):
        self.web.camera_local_enable("phone-1")
        self.web.camera_frame(
            "phone-1", base64.b64encode(b"jpeg").decode("ascii"), "webrtc", 640, 480
        )
        result = self.web.camera_observation("phone-1")
        self.assertEqual(result["source"], "camera_bridge")
        self.assertEqual(result["authority"], "none")
        self.assertFalse(result["permission_granted"])
        self.assertFalse(result["trusted_instruction"])

    def test_local_disable_clears_frame_and_blocks_remote_submit(self):
        self.web.camera_local_enable("phone-1")
        self.web.camera_frame(
            "phone-1", base64.b64encode(b"jpeg").decode("ascii"), "jpeg", 640, 480
        )
        self.web.camera_local_disable("phone-1")
        self.assertIsNone(self.web.camera_observation("phone-1"))
        with self.assertRaises(PermissionError):
            self.web.camera_frame(
                "phone-1", base64.b64encode(b"jpeg").decode("ascii"), "jpeg", 640, 480
            )


if __name__ == "__main__":
    unittest.main()
