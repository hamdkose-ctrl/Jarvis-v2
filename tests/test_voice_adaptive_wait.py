"""Konuşma süresine göre bekleme (modelsiz sıra kararı)."""
import unittest
from modules import voice_turn


class AdaptiveWait(unittest.TestCase):
    def test_short_answer_waits_short(self):
        self.assertLess(voice_turn.adaptive_wait(1.5), 1.5)

    def test_long_answer_waits_longer(self):
        self.assertGreater(voice_turn.adaptive_wait(8.0), voice_turn.adaptive_wait(1.5))

    def test_bounds_are_respected(self):
        self.assertGreaterEqual(voice_turn.adaptive_wait(0.0), voice_turn.ADAPTIVE_MIN_SECS)
        self.assertLessEqual(voice_turn.adaptive_wait(60.0), voice_turn.ADAPTIVE_MAX_SECS)

    def test_dangling_waits_longer_but_capped(self):
        self.assertGreater(voice_turn.adaptive_wait(3.0, complete=False),
                           voice_turn.adaptive_wait(3.0, complete=True))
        self.assertLessEqual(voice_turn.adaptive_wait(60.0, complete=False),
                             voice_turn.ADAPTIVE_DANGLING_MAX_SECS)

    def test_unknown_duration_keeps_old_behaviour(self):
        self.assertEqual(voice_turn.adaptive_wait(None, complete=True), voice_turn.FINISHED_WAIT_SECS)
        self.assertEqual(voice_turn.adaptive_wait(None, complete=False), voice_turn.MAX_WAIT_SECS)


if __name__ == "__main__":
    unittest.main()
