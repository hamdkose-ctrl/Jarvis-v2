"""Regression for Windows sharing violations during atomic ExecutionRecord writes.

No live Windows device or external provider is needed: the file-open denial
is injected at the same Path.read_text boundary as the PC watcher traceback.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from modules import execution_record


OWNER = 'alice'
JOB = '0123456789abcdef'


class ExecutionRecordWindowsOpenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = execution_record.path_for(self.root, JOB)
        self.path.write_bytes(execution_record.encode({
            'id': JOB, 'owner': OWNER, 'request': 'Read safely',
            'state': 'running', 'goals': [], 'steps': [], 'outputs': {},
        }))

    def test_transient_denied_open_retries_and_loads_exact_owner(self):
        original = Path.read_text
        attempts = []

        def intermittently_denied(path, *args, **kwargs):
            attempts.append(path)
            if len(attempts) <= 2:
                raise PermissionError(13, 'Permission denied', str(path))
            return original(path, *args, **kwargs)

        with patch.object(execution_record, '_WINDOWS', True), \
             patch.object(Path, 'read_text', new=intermittently_denied), \
             patch.object(execution_record.time, 'sleep') as sleeping:
            loaded = execution_record.load(self.root, OWNER, JOB)

        self.assertEqual(loaded['id'], JOB)
        self.assertEqual(attempts, [self.path] * 3)
        self.assertEqual(sleeping.call_args_list, [call(0.01), call(0.02)])

    def test_persistent_permission_denial_stays_denied(self):
        with patch.object(execution_record, '_WINDOWS', True), \
             patch.object(Path, 'read_text', side_effect=PermissionError(13, 'Denied')) as opening, \
             patch.object(execution_record.time, 'sleep') as sleeping:
            with self.assertRaises(PermissionError):
                execution_record.load(self.root, OWNER, JOB)

        self.assertEqual(opening.call_count, len(execution_record._READ_RETRY_DELAYS))
        self.assertEqual(sleeping.call_count, len(execution_record._READ_RETRY_DELAYS) - 1)

    def test_non_windows_denial_is_not_retried(self):
        with patch.object(execution_record, '_WINDOWS', False), \
             patch.object(Path, 'read_text', side_effect=PermissionError(13, 'Denied')) as opening, \
             patch.object(execution_record.time, 'sleep') as sleeping:
            with self.assertRaises(PermissionError):
                execution_record.load(self.root, OWNER, JOB)

        opening.assert_called_once()
        sleeping.assert_not_called()

    def test_bad_json_is_never_retried_or_accepted(self):
        with patch.object(execution_record, '_WINDOWS', True), \
             patch.object(Path, 'read_text', return_value='{broken') as opening, \
             patch.object(execution_record.time, 'sleep') as sleeping:
            with self.assertRaises(ValueError):
                execution_record.load(self.root, OWNER, JOB)

        opening.assert_called_once()
        sleeping.assert_not_called()

    def test_wrong_owner_is_not_accepted_or_retried(self):
        original = Path.read_text
        calls = []

        def observed_read(path, *args, **kwargs):
            calls.append(path)
            return original(path, *args, **kwargs)

        with patch.object(execution_record, '_WINDOWS', True), \
             patch.object(Path, 'read_text', new=observed_read), \
             patch.object(execution_record.time, 'sleep') as sleeping:
            with self.assertRaises(PermissionError):
                execution_record.load(self.root, 'bob', JOB)
        self.assertEqual(calls, [self.path])
        sleeping.assert_not_called()

    def test_symlink_rejected_without_open_retry(self):
        with patch.object(execution_record, '_WINDOWS', True), \
             patch.object(Path, 'is_symlink', return_value=True), \
             patch.object(Path, 'read_text') as opening, \
             patch.object(execution_record.time, 'sleep') as sleeping:
            with self.assertRaises(ValueError):
                execution_record.load(self.root, OWNER, JOB)

        opening.assert_not_called()
        sleeping.assert_not_called()


if __name__ == '__main__':
    unittest.main()
