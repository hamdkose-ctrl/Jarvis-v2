"""Mikrofon sessizlik eşiği: ayar kapalıyken eski davranış, açıkken süreye göre."""
import unittest
from unittest.mock import patch

from modules import voice


class AdaptiveSilence(unittest.TestCase):
    def test_disabled_keeps_old_threshold(self):
        with patch.object(voice, "_adaptive_wait_enabled", return_value=False):
            self.assertEqual(voice._silence_needed(500, 15), 15)

    def test_enabled_waits_longer_after_long_speech(self):
        with patch.object(voice, "_adaptive_wait_enabled", return_value=True):
            short = voice._silence_needed(15, 15)     # ~0,9 sn konuşma
            long = voice._silence_needed(150, 15)     # ~8 sn konuşma
        self.assertGreater(long, short)
        self.assertGreaterEqual(short, 1)

    def test_never_returns_zero(self):
        with patch.object(voice, "_adaptive_wait_enabled", return_value=True):
            self.assertGreaterEqual(voice._silence_needed(0, 15), 1)


if __name__ == "__main__":
    unittest.main()
