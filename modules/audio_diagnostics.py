"""Opt-in bounded, local recordings of input and successful send calls."""
import collections
import wave
import numpy as np


class AudioDiagnostics:
    def __init__(self):
        self.raw = collections.deque(maxlen=400)
        self.sent = collections.deque(maxlen=400)

    def input(self, now, pcm, rate):
        self.raw.append((now, bytes(pcm), int(rate)))

    def output(self, now, pcm, rate=16000):
        self.sent.append((now, bytes(pcm), int(rate)))

    @staticmethod
    def _render(records, end, rate):
        samples = np.zeros(30 * rate, dtype=np.int16)
        for stamp, pcm, source_rate in records:
            if source_rate != rate:
                continue  # a hardware rate change is not silently resampled
            values = np.frombuffer(pcm, dtype='<i2')
            start = round((stamp - (end - 30)) * rate) - len(values)
            left, right = max(0, start), min(len(samples), start + len(values))
            if right > left:
                samples[left:right] = values[left-start:right-start]
        return samples.astype('<i2').tobytes()

    def save(self, directory, end):
        if not self.raw:
            return
        rate = self.raw[-1][2]
        for name, records, sample_rate in (
            ('tani_mikrofon.wav', self.raw, rate),
            ('tani_gonderilen.wav', self.sent, 16000),
        ):
            with wave.open(str(directory / name), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(sample_rate)
                stream.writeframes(self._render(records, end, sample_rate))
