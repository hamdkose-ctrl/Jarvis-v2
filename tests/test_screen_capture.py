import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import screen_capture as sc, nxapi


class ScreenCaptureTests(unittest.TestCase):
    def runtime(self):
        return SimpleNamespace(sys=SimpleNamespace(platform='win32'),
                               time=SimpleNamespace(sleep=Mock()), _win_action=Mock(return_value=True))

    def test_drag_reverse_clamp_and_small_selection(self):
        self.assertEqual(sc.selection_box((90, 80), (-5, 200), (100, 100)), (0, 80, 90, 100))
        self.assertIsNone(sc.selection_box((10, 10), (11, 50), (100, 100)))

    def test_cancel_restores_window_without_saving(self):
        runtime = self.runtime()
        with patch.object(sc.subprocess, 'run', return_value=SimpleNamespace(returncode=2)), patch.object(nxapi, 'save_upload') as save:
            self.assertEqual(sc.capture(runtime), {'cancelled': True})
            save.assert_not_called()
        self.assertEqual(runtime._win_action.call_args_list, [(('hide',),), (('show',),)])
        self.assertFalse(sc._LOCK.locked())

    def test_error_and_timeout_restore_window(self):
        for result in (SimpleNamespace(returncode=1), subprocess.TimeoutExpired('selector', 120)):
            runtime = self.runtime()
            kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with patch.object(sc.subprocess, 'run', **kwargs), self.assertRaises(ValueError):
                sc.capture(runtime)
            runtime._win_action.assert_called_with('show')
            self.assertFalse(sc._LOCK.locked())

    def test_success_saves_full_image_and_bounded_preview(self):
        from PIL import Image
        runtime = self.runtime()
        def select(command, **kwargs):
            Image.new('RGB', (1600, 900), 'blue').save(command[-1])
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as folder, patch.object(nxapi, 'FILES_DIR', Path(folder)), patch.object(sc.subprocess, 'run', side_effect=select):
            result = sc.capture(runtime)
            self.assertTrue(result['preview'].startswith('data:image/png;base64,'))
            with Image.open(result['path']) as image:
                self.assertEqual(image.size, (1600, 900))
            self.assertEqual(len(list(Path(folder).glob('*.png'))), 1)
        runtime._win_action.assert_called_with('show')

    def test_hide_failure_does_not_capture(self):
        runtime = self.runtime(); runtime._win_action.return_value = False
        with patch.object(sc.subprocess, 'run') as run, self.assertRaises(ValueError):
            sc.capture(runtime)
        run.assert_not_called()
        self.assertFalse(sc._LOCK.locked())
