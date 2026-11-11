"""BRAIN-07: cross-process file-effect path claims, real temp files only."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_ops, file_resource_guard


_HOLD = """
import sys
import time
from pathlib import Path
from modules import file_resource_guard
file_resource_guard.DATA_DIR = Path(sys.argv[1])
with file_resource_guard.claim_paths(Path(sys.argv[2])):
    Path(sys.argv[3]).write_text('held', encoding='utf-8')
    time.sleep(30)
"""


class FileEffectClaimTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.folder = self.base / 'Belgeler'
        self.folder.mkdir()
        for obj, attr, value in (
            (file_resource_guard, 'DATA_DIR', self.base / 'claims'),
            (file_ops, 'DATA_DIR', self.base / 'journal'),
            (file_ops, '_roots', lambda: [self.folder]),
            (file_ops, '_permission_decision', lambda *_: None),
        ):
            p = patch.object(obj, attr, value)
            p.start()
            self.addCleanup(p.stop)
        file_ops.DATA_DIR.mkdir()
        self.cwd = Path(__file__).resolve().parents[1]

    def holder(self, path):
        flag = self.base / 'held.flag'
        if flag.exists():
            flag.unlink()
        child = subprocess.Popen(
            [sys.executable, '-c', _HOLD, str(file_resource_guard.DATA_DIR),
             str(path), str(flag)],
            cwd=self.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 8
        while not flag.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        if not flag.exists():
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            error = child.stderr.read().decode('utf-8', errors='replace')
            child.stderr.close()
            self.fail('File claim child failed to start: ' + error)
        return child

    def close_holder(self, child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        child.stderr.close()

    def test_rename_same_source_is_rejected_then_released(self):
        target = self.folder / 'original.txt'
        target.write_text('original', encoding='utf-8')
        child = self.holder(target)
        try:
            message = file_ops.execute_typed(
                'rename', owner='alice', path=str(target), name='renamed.txt',
            )
            self.assertIn('başka bir işlem', message)
            self.assertEqual(target.read_text(encoding='utf-8'), 'original')
            self.assertFalse((self.folder / 'renamed.txt').exists())
        finally:
            self.close_holder(child)
        done = file_ops.execute_typed(
            'rename', owner='alice', path=str(target), name='renamed.txt',
        )
        self.assertIn('adını', done)
        self.assertEqual((self.folder / 'renamed.txt').read_text(encoding='utf-8'), 'original')

    def test_independent_file_is_not_blocked_by_occupied_source(self):
        source = self.folder / 'held.txt'
        other = self.folder / 'free.txt'
        source.write_text('held', encoding='utf-8')
        other.write_text('free', encoding='utf-8')
        child = self.holder(source)
        try:
            done = file_ops.execute_typed(
                'rename', owner='alice', path=str(other), name='changed.txt',
            )
            self.assertIn('adını', done)
            self.assertEqual((self.folder / 'changed.txt').read_text(encoding='utf-8'), 'free')
        finally:
            self.close_holder(child)

    def test_create_claim_blocks_competing_basename_before_write(self):
        expected = self.folder / 'note.txt'
        child = self.holder(expected)
        try:
            with patch.object(file_ops.files, 'match_folder',
                              return_value=(self.folder, 'Belgeler', False)):
                message = file_ops.execute_typed(
                    'create', owner='alice', folder='belgeler',
                    name='note.txt', content='hello',
                )
            self.assertIn('başka bir işlem', message)
            self.assertFalse(expected.exists())
        finally:
            self.close_holder(child)

    def test_symlink_destination_is_rejected_without_writing(self):
        source = self.folder / 'source.txt'
        source.write_text('safe', encoding='utf-8')
        target = self.folder / 'rename.txt'
        try:
            target.symlink_to(source)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable on this platform')
        message = file_ops.execute_typed(
            'rename', owner='alice', path=str(source), name='rename.txt',
        )
        self.assertIn('başka bir işlem', message)
        self.assertEqual(source.read_text(encoding='utf-8'), 'safe')


if __name__ == '__main__':
    unittest.main()
