"""Camera/WebRTC bridge safety contract.

Benchmark pattern is reimplemented without copying source code. The bridge is an
observation adapter only; it never grants authority or permission.
"""
from __future__ import annotations

import unittest

from modules import camera_bridge


class CameraBridgeTests(unittest.TestCase):
    def setUp(self):
        camera_bridge._reset_for_tests()

    def test_remote_cannot_start_camera_before_local_enable(self):
        with self.assertRaises(PermissionError):
            camera_bridge.submit_frame(
                "hamdi", "phone-1", b"jpeg", transport="webrtc", width=640, height=480
            )

    def test_local_stop_wins_until_local_reenable(self):
        camera_bridge.local_enable("hamdi", "phone-1")
        camera_bridge.submit_frame(
            "hamdi", "phone-1", b"first", transport="webrtc", width=640, height=480
        )
        camera_bridge.local_disable("hamdi", "phone-1")
        with self.assertRaises(PermissionError):
            camera_bridge.submit_frame(
                "hamdi", "phone-1", b"second", transport="webrtc", width=640, height=480
            )
        camera_bridge.local_enable("hamdi", "phone-1")
        obs = camera_bridge.submit_frame(
            "hamdi", "phone-1", b"third", transport="webrtc", width=640, height=480
        )
        self.assertEqual(obs["device_id"], "phone-1")

    def test_observation_never_grants_authority_or_permission(self):
        camera_bridge.local_enable("hamdi", "phone-1")
        obs = camera_bridge.submit_frame(
            "hamdi", "phone-1", b"jpeg", transport="jpeg", width=1280, height=720
        )
        self.assertEqual(obs["authority"], "none")
        self.assertFalse(obs["permission_granted"])
        self.assertFalse(obs["trusted_instruction"])
        self.assertEqual(obs["retention"], "ephemeral")

    def test_owner_isolation(self):
        camera_bridge.local_enable("hamdi", "phone-1")
        camera_bridge.submit_frame(
            "hamdi", "phone-1", b"jpeg", transport="webrtc", width=640, height=480
        )
        self.assertIsNone(camera_bridge.latest("hasan", "phone-1"))

    def test_stale_frame_is_not_returned(self):
        camera_bridge.local_enable("hamdi", "phone-1")
        camera_bridge.submit_frame(
            "hamdi", "phone-1", b"jpeg", transport="webrtc", width=640, height=480, now=10.0
        )
        self.assertIsNone(camera_bridge.latest("hamdi", "phone-1", max_age=2.0, now=13.1))

    def test_transport_and_frame_limits_fail_closed(self):
        camera_bridge.local_enable("hamdi", "phone-1")
        with self.assertRaises(ValueError):
            camera_bridge.submit_frame(
                "hamdi", "phone-1", b"x", transport="socket", width=640, height=480
            )
        with self.assertRaises(ValueError):
            camera_bridge.submit_frame(
                "hamdi", "phone-1", b"x" * (camera_bridge.MAX_FRAME_BYTES + 1),
                transport="jpeg", width=640, height=480
            )

    def test_max_three_viewers_and_local_stop_disconnects(self):
        camera_bridge.local_enable("hamdi", "phone-1")
        self.assertEqual(camera_bridge.viewer_join("hamdi", "phone-1", "a"), 1)
        self.assertEqual(camera_bridge.viewer_join("hamdi", "phone-1", "b"), 2)
        self.assertEqual(camera_bridge.viewer_join("hamdi", "phone-1", "c"), 3)
        with self.assertRaises(RuntimeError):
            camera_bridge.viewer_join("hamdi", "phone-1", "d")
        camera_bridge.local_disable("hamdi", "phone-1")
        self.assertEqual(camera_bridge.status("hamdi", "phone-1")["viewers"], 0)


if __name__ == "__main__":
    unittest.main()
