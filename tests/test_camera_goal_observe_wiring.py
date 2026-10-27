from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import goal_tools


class CameraGoalObserveWiringTests(unittest.TestCase):
    def _runtime(self):
        profile = SimpleNamespace(slug='hamdi')
        vision = SimpleNamespace(mode=lambda: 'camera', snapshot_path=lambda: None)
        return SimpleNamespace(
            profile=profile,
            _cur_source='yazı',
            pc_profile=lambda: profile,
            vision=vision,
            ask_image=lambda path, question, guard, strict=False: 'görüntü sonucu',
        )

    def test_camera_target_is_valid_remote_device_selector(self):
        data = {'kind':'camera','question':'Ne görüyorsun?','target':'phone-1'}
        self.assertEqual(data, goal_tools.validate('observe', data))

    def test_remote_camera_snapshot_uses_existing_strict_vision_path(self):
        runtime = self._runtime()
        fd, name = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        Path(name).write_bytes(b'jpeg')
        try:
            with patch('modules.camera_bridge.snapshot_path', return_value=name) as snapshot:
                result = goal_tools.execute(
                    runtime,
                    'observe',
                    {'kind':'camera','question':'Ne görüyorsun?','target':'phone-1'},
                    {},
                    {'job_id':'j1','task_id':'t1','request':'telefon kamerasını incele'},
                )
            snapshot.assert_called_once_with('hamdi', 'phone-1')
            self.assertEqual(result['state'], 'done')
            self.assertEqual(result['local_evidence'], 'observe')
            self.assertFalse(Path(name).exists())
        finally:
            Path(name).unlink(missing_ok=True)

    def test_local_camera_without_target_keeps_existing_share_precondition(self):
        runtime = self._runtime()
        runtime.vision = SimpleNamespace(mode=lambda: None, snapshot_path=lambda: None)
        with self.assertRaises(goal_tools.NotStarted):
            goal_tools.execute(
                runtime,
                'observe',
                {'kind':'camera','question':'Ne görüyorsun?'},
                {},
                {'job_id':'j1','task_id':'t1','request':'kamerayı incele'},
            )


if __name__ == '__main__':
    unittest.main()
