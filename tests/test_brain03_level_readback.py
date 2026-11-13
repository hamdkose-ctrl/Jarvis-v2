"""BRAIN-03: direct Windows level success requires independently observed state."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from modules import engine_intents, session_state


class VolumeReadbackTests(unittest.TestCase):
    def setUp(self):
        self.state = session_state.SessionState()
        self.control = Mock()
        self.ctx = SimpleNamespace(_session=lambda: self.state,
                                   system_control=self.control)

    def level(self, target=20):
        return engine_intents.dispatch(self.ctx, "level_set",
                                       {"property": "volume", "level": target},
                                       f"sesi {target} yap", "")

    def test_verified_volume_is_reported_and_remembered(self):
        self.control.set_volume.return_value = True
        self.control.current_volume.return_value = 20
        result = self.level()
        self.assertTrue(result.ok)
        self.assertIn("yaptım", result)
        self.control.set_volume.assert_called_once_with(20)
        self.control.current_volume.assert_called_once_with()
        self.assertEqual(session_state.fresh_property(self.state), "volume")

    def test_unverified_write_is_not_success_and_does_not_remember(self):
        for measured in (None, 0, 19, 21, True, "20"):
            with self.subTest(measured=measured):
                self.state = session_state.SessionState()
                self.control.reset_mock()
                self.control.set_volume.return_value = True
                self.control.current_volume.return_value = measured
                result = self.level()
                self.assertFalse(result.ok)
                self.assertNotIn("yaptım", result)
                self.assertIn("doğrulayamadım", result)
                self.assertIsNone(session_state.fresh_property(self.state))

    def test_failed_adjustment_invalidates_prior_verified_other_property(self):
        # After a failed brightness/volume attempt a subsequent bare "20"
        # must not silently reuse an older and now misleading target.
        session_state.remember_property(self.state, "brightness")
        self.control.set_volume.return_value = True
        self.control.current_volume.return_value = 19
        result = self.level(20)
        self.assertFalse(result.ok)
        self.assertIsNone(session_state.fresh_property(self.state))

    def test_failed_volume_api_never_claims_success_or_reads_back(self):
        self.control.set_volume.return_value = False
        result = self.level()
        self.assertFalse(result.ok)
        self.assertNotIn("yaptım", result)
        self.control.current_volume.assert_not_called()
        self.assertIsNone(session_state.fresh_property(self.state))


if __name__ == "__main__":
    unittest.main()
