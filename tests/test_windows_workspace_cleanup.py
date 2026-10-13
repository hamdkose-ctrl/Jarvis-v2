"""Sharing violations during scratch cleanup must not change validation results."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import release_guard as guard
from modules import release_workspace as workspace


def locked():
    error = PermissionError('Windows sharing violation')
    error.winerror = 32
    return error


class WindowsWorkspaceCleanupTests(unittest.TestCase):
    def test_transient_lock_retries_then_removes_real_workspace(self):
        remove = shutil.rmtree
        calls = []
        def retry(path, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                raise locked()
            return remove(path, **kwargs)
        with patch.object(guard.shutil, 'rmtree', side_effect=retry), patch.object(guard.time, 'sleep'):
            with guard.temporary_workspace('jarvis-cleanup-test-') as folder:
                (folder/'sample.txt').write_text('scratch')
        self.assertEqual(len(calls), 2)
        self.assertFalse(folder.exists())

    def test_persistent_lock_preserves_body_failure_and_logs_deferral(self):
        folder = None
        try:
            with patch.object(guard.shutil, 'rmtree', side_effect=locked()), patch.object(guard.time, 'sleep'), self.assertLogs('release_guard', level='WARNING'):
                with self.assertRaisesRegex(RuntimeError, 'real test failure'):
                    with guard.temporary_workspace('jarvis-cleanup-test-') as folder:
                        raise RuntimeError('real test failure')
            self.assertTrue(folder.exists())
        finally:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)

    def test_non_sharing_error_is_not_ignored(self):
        folder = None
        try:
            with patch.object(guard.shutil, 'rmtree', side_effect=OSError('disk failure')):
                with self.assertRaisesRegex(OSError, 'disk failure'):
                    with guard.temporary_workspace('jarvis-cleanup-test-') as folder:
                        pass
        finally:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)

    def test_baseline_cleanup_lock_does_not_turn_pass_or_failure_into_exception(self):
        with tempfile.TemporaryDirectory() as outer:
            project = Path(outer)/'project';project.mkdir();(project/'main.py').write_text('old = 1')
            temporary = []
            remove = shutil.rmtree
            def block_baseline(path, **kwargs):
                if Path(path).name.startswith('jarvis-trusted-tests-'):
                    if path not in temporary:
                        temporary.append(path)
                    raise locked()
                return remove(path, **kwargs)
            try:
                for expected in [(True, 'tests passed'), (False, 'real regression')]:
                    with patch.object(guard.shutil, 'rmtree', side_effect=block_baseline), patch.object(guard.time, 'sleep'), patch('modules.validation.run_checks', return_value=expected), self.assertLogs('release_guard', level='WARNING'):
                        self.assertEqual(workspace.validate(project, project), expected)
                self.assertEqual((project/'main.py').read_text(), 'old = 1')
            finally:
                for folder in temporary:
                    shutil.rmtree(folder, ignore_errors=True)
