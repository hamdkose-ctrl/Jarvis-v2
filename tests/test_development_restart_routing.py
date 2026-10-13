import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from modules import developer as dev


class DevelopmentRestartRoutingTests(unittest.TestCase):
    def test_locked_persisted_mode_leaves_normal_chat_and_images_available(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dev, 'STORE', Path(directory)), patch.object(dev, '_AUTH', set()):
            dev.unlock('alice', 'test-pass')
            dev.enable('alice')
            dev._AUTH.clear()
            self.assertFalse(dev.status('alice')['enabled'])
            self.assertIsNone(dev.handle('alice', 'bu görseli analiz et'))
            self.assertIsNone(dev.handle('alice', 'görselin metnini çıkar'))
            self.assertIsNone(dev.handle('alice', 'çalışmaya başla'))
            self.assertIn('kilitli', dev.handle('alice', 'değişiklikleri uygula'))
            self.assertTrue(dev.unlock('alice', 'test-pass')['ok'])
            self.assertTrue(dev.status('alice')['enabled'])
