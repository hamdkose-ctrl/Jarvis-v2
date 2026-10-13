"""Content-free first-response timing; output writes are not hardware playback acknowledgements."""
import logging
import threading
import time


class VoiceTiming:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = {}

    def begin(self):
        with self.lock:
            self.events = {'wake': time.monotonic()}

    def note(self, stage):
        with self.lock:
            if 'wake' not in self.events or stage in self.events:
                return
            if stage == 'output_write' and 'reply_audio' not in self.events:
                return
            now = time.monotonic()
            self.events[stage] = now
            elapsed = now - self.events['wake']
        logging.getLogger('jarvis').info('Ses zamanlaması: %s, uyanmadan %.3f sn sonra', stage, elapsed)
