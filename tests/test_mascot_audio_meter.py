import struct
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import mascot_audio_meter as meter


class MascotAudioMeterTests(unittest.TestCase):
    def tearDown(self):
        meter.enable(False)

    def test_sample_is_visible_only_at_device_time(self):
        meter.enable(True)
        cancel = threading.Event()
        info = SimpleNamespace(outputBufferDacTime=10.35, currentTime=10)
        with patch.object(meter.time, "monotonic", return_value=100.0):
            meter.observe(struct.pack("<1024h", *([5000] * 1024)), 1024, 24000, info, cancel)
        self.assertEqual(meter.aperture(100.1), 0.0)
        self.assertGreater(meter.aperture(100.37), 0.5)
        self.assertEqual(meter.aperture(100.5), 0.0)
        cancel.set()
        self.assertEqual(meter.aperture(100.37), 0.0)

    def test_silence_disabled_and_invalid(self):
        cancel = threading.Event()
        with patch.object(meter.time, "monotonic", return_value=5.0):
            meter.observe(struct.pack("<20h", *([10000] * 20)), 20, 1000, None, cancel)
            self.assertEqual(meter.aperture(5.01), 0.0)
            meter.enable(True)
            meter.observe(bytes(40), 20, 1000, None, cancel)
            meter.observe(b"x", 20, 1000, None, cancel)
            self.assertEqual(meter.aperture(5.01), 0.0)

    def test_history_is_bounded(self):
        meter.enable(True)
        cancel = threading.Event()
        for _ in range(100):
            meter.observe(bytes(40), 20, 1000, None, cancel)
        self.assertLessEqual(len(meter._samples), 64)
        meter.enable(False)
        self.assertEqual(meter._samples, ())


if __name__ == "__main__":
    unittest.main()
