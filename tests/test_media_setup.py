import shutil
import subprocess
import unittest
from unittest.mock import patch
from modules import media_setup


class MediaSetupTests(unittest.TestCase):
    def test_missing_tools_never_run_commands(self):
        with patch.object(media_setup.shutil,'which',return_value=None),patch.object(media_setup.subprocess,'run') as run:
            self.assertFalse(media_setup.check()['ok']);run.assert_not_called()

    def test_broken_tool_does_not_disclose_raw_error(self):
        with patch.object(media_setup.shutil,'which',return_value='tool'),patch.object(media_setup.subprocess,'run',side_effect=OSError('PRIVATE_PATH')):
            result=media_setup.check();self.assertFalse(result['ok']);self.assertNotIn('PRIVATE_PATH',result['text'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Video araçları kurulu değil')
    def test_real_video_can_be_encoded_and_probed(self):
        self.assertTrue(media_setup.check()['ok'])

    def test_timeout_is_not_reported_as_success(self):
        with patch.object(media_setup.shutil,'which',return_value='tool'),patch.object(media_setup.subprocess,'run',side_effect=subprocess.TimeoutExpired('tool',5)):
            self.assertFalse(media_setup.check()['ok'])
