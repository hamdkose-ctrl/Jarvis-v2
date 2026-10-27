from __future__ import annotations

import unittest

import gesture_adapter


class GestureInputAdapterTests(unittest.TestCase):
    def setUp(self):
        gesture_adapter._reset_for_tests()

    def test_single_frame_and_transition_window_do_not_emit(self):
        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-1', 'thumbs_up', now=10.0))
        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-1', 'thumbs_up', now=10.34))
        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-1', 'thumbs_up', now=11.34))
        event = gesture_adapter.sample('hamdi', 'phone-1', 'thumbs_up', now=11.35)
        self.assertEqual(event['intent'], 'select_suggestion')

    def test_event_is_input_signal_not_authority_or_permission(self):
        gesture_adapter.sample('hamdi', 'phone-1', 'open_palm', now=20.0)
        event = gesture_adapter.sample('hamdi', 'phone-1', 'open_palm', now=21.25)
        self.assertEqual(event['source'], 'gesture_adapter')
        self.assertEqual(event['authority'], 'none')
        self.assertFalse(event['permission_granted'])
        self.assertFalse(event['trusted_instruction'])
        self.assertEqual(event['retention'], 'ephemeral')
        self.assertTrue(event['requires_policy'])

    def test_latched_gesture_does_not_repeat_until_release(self):
        gesture_adapter.sample('hamdi', 'phone-1', 'point_right', now=30.0)
        first = gesture_adapter.sample('hamdi', 'phone-1', 'point_right', now=31.25)
        self.assertEqual(first['intent'], 'menu_next')
        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-1', 'point_right', now=33.0))

        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-1', 'none', now=33.1))
        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-1', 'point_right', now=33.2))
        second = gesture_adapter.sample('hamdi', 'phone-1', 'point_right', now=34.45)
        self.assertEqual(second['intent'], 'menu_next')

    def test_cooldown_blocks_fast_retrigger_after_release(self):
        gesture_adapter.sample('hamdi', 'phone-1', 'open_palm', now=60.0)
        first = gesture_adapter.sample('hamdi', 'phone-1', 'open_palm', now=61.25)
        self.assertEqual(first['intent'], 'stop')
        gesture_adapter.sample('hamdi', 'phone-1', 'none', now=61.30)
        gesture_adapter.sample('hamdi', 'phone-1', 'open_palm', now=61.31)
        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-1', 'open_palm', now=62.56))
        second = gesture_adapter.sample('hamdi', 'phone-1', 'open_palm', now=62.76)
        self.assertEqual(second['intent'], 'stop')

    def test_owner_and_device_state_are_isolated(self):
        gesture_adapter.sample('hamdi', 'phone-1', 'fist', now=40.0)
        self.assertIsNone(gesture_adapter.sample('hamdi', 'phone-2', 'fist', now=42.2))
        self.assertIsNone(gesture_adapter.sample('hasan', 'phone-1', 'fist', now=42.2))
        event = gesture_adapter.sample('hamdi', 'phone-1', 'fist', now=42.15)
        self.assertEqual(event['intent'], 'mute_local')
        self.assertEqual(event['owner'], 'hamdi')
        self.assertEqual(event['device_id'], 'phone-1')

    def test_unknown_gesture_is_rejected_fail_closed(self):
        with self.assertRaises(ValueError):
            gesture_adapter.sample('hamdi', 'phone-1', 'send_mail', now=50.0)


if __name__ == '__main__':
    unittest.main()
