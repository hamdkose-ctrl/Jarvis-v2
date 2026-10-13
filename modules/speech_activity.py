"""Local activity is timing evidence, never a transcript or a command."""
import collections
import numpy as np


class SpeechActivity:
    def __init__(self):
        self.levels = collections.deque(maxlen=250)
        self.reset()

    def reset(self):
        self.last = None
        self.streak = 0

    def observe(self, pcm, now):
        level = float(np.abs(pcm.astype(np.int32)).mean()) if len(pcm) else 0.0
        # Use pre-gain input; amplification of quiet noise must not count as speech.
        floor = float(np.percentile(self.levels, 20)) if self.levels else level
        self.levels.append(level)
        if level > max(60.0, floor * 3.0):
            self.streak += 1
        else:
            self.streak = 0
        if self.streak >= 3:  # three 80 ms frames; a click alone is insufficient
            self.last = now

    def expired(self, now, started, timeout):
        elapsed = now - started
        # Give locally detected speech time to be transcribed, but never hold a
        # failed recognizer open indefinitely on noise alone.
        hard_limit = max(60.0, timeout * 4.0)
        quiet = now - (self.last if self.last is not None else started)
        return elapsed >= hard_limit or (elapsed > timeout and quiet > timeout)
