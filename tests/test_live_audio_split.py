import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from modules import live_audio

class AudioSplitTests(unittest.TestCase):
    def test_streaming_resample_preserves_duration_and_finite_samples(self):
        convert=live_audio._Resampler(48000)
        signal=(np.sin(np.arange(48000)*2*np.pi*400/48000)*8000).astype(np.int16)
        output=np.concatenate([convert(x) for x in np.array_split(signal,50)])
        self.assertTrue(15900<len(output)<16100)
        self.assertEqual(output.dtype,np.int16)
        self.assertTrue(np.isfinite(output).all())
        self.assertGreater(np.abs(output).max(),5000)
    def test_mute_does_not_open_or_write_speaker(self):
        player=live_audio._Player.__new__(live_audio._Player)
        player.runtime=SimpleNamespace(speak_allowed=lambda:False,RECV_RATE=24000)
        with patch.object(live_audio.time,'sleep') as sleep,patch.object(player,'_open',side_effect=AssertionError('opened speaker')):
            player._write(b'\0'*4800)
        sleep.assert_called_once_with(.1)
