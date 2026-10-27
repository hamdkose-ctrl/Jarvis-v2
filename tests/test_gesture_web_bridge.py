from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from web_chat import WebChat


class GestureWebBridgeTests(unittest.TestCase):
    def _bridge(self):
        runtime = SimpleNamespace(
            _p=lambda: SimpleNamespace(slug='hamdi'),
            engine=SimpleNamespace(submit=Mock()),
        )
        bridge = WebChat()
        bridge._runtime = runtime
        return bridge, runtime

    def test_gesture_sample_uses_active_owner_and_returns_normalized_event(self):
        bridge, runtime = self._bridge()
        normalized = {
            'owner': 'hamdi',
            'device_id': 'phone-1',
            'gesture': 'open_palm',
            'intent': 'stop',
            'source': 'gesture_adapter',
            'authority': 'none',
            'permission_granted': False,
            'trusted_instruction': False,
            'retention': 'ephemeral',
            'requires_policy': True,
        }
        with patch('gesture_adapter.sample', return_value=normalized) as sample:
            result = bridge.gesture_sample('phone-1', 'open_palm')
        sample.assert_called_once_with('hamdi', 'phone-1', 'open_palm')
        self.assertEqual(result, normalized)
        runtime.engine.submit.assert_not_called()

    def test_gesture_sample_can_return_none_without_side_effect(self):
        bridge, runtime = self._bridge()
        with patch('gesture_adapter.sample', return_value=None) as sample:
            result = bridge.gesture_sample('phone-1', 'thumbs_up')
        sample.assert_called_once_with('hamdi', 'phone-1', 'thumbs_up')
        self.assertIsNone(result)
        runtime.engine.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
