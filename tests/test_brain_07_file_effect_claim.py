"""BRAIN-07: cross-process file-effect path claims, real temp files only."""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_ops, file_resource_guard, file_worker_extensions


_HOLD = """
import sys
import time
from pathlib import Path
from modules import file_resource_guard
if file_resource_guard._FILE_EFFECT_CLAIM_ROOT != Path(sys.argv[1]):
    raise RuntimeError('Physical file claim root incorrectly follows DATA_DIR')
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
        self.fake_home = self.base / 'same-os-account-home'
        self.fake_home.mkdir()
        for obj, attr, value in (
            (file_resource_guard, '_FILE_EFFECT_CLAIM_ROOT',
             self.fake_home / '.jarvis' / 'file-effect-claims'),
            (file_ops, 'DATA_DIR', self.base / 'journal'),
            (file_ops, '_roots', lambda: [self.folder]),
            (file_ops, '_permission_decision', lambda *_: None),
        ):
            p = patch.object(obj, attr, value)
            p.start()
            self.addCleanup(p.stop)
        file_ops.DATA_DIR.mkdir()
        self.cwd = Path(__file__).resolve().parents[1]

    def holder(self, path, *, other_data_dir=False):
        flag = self.base / 'held.flag'
        if flag.exists():
            flag.unlink()
        env = os.environ.copy()
        # The second Python process derives its claim root naturally at
        # import time from the same synthetic OS home, not an injected lock.
        env['HOME'] = str(self.fake_home)
        env['USERPROFILE'] = str(self.fake_home)
        if other_data_dir:
            env['JARVIS_DATA_DIR'] = str(self.base / 'different-jarvis-data')
        child = subprocess.Popen(
            [sys.executable, '-c', _HOLD,
             str(file_resource_guard._FILE_EFFECT_CLAIM_ROOT),
             str(path), str(flag)],
            cwd=self.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env=env,
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

    def test_distinct_data_roots_share_one_physical_file_claim(self):
        """Two Jarvis instances on one OS account cannot claim the same file.

        The helper starts with a different JARVIS_DATA_DIR; the trusted
        physical claim root is deliberately identical. An unrelated file
        remains independent, and OS release after child death is proved.
        """
        shared = self.folder / 'shared.txt'
        unrelated = self.folder / 'independent.txt'
        shared.write_text('original', encoding='utf-8')
        unrelated.write_text('other', encoding='utf-8')
        child = self.holder(shared, other_data_dir=True)
        try:
            with self.assertRaises(file_resource_guard.resource_leases.LeaseConflict):
                with file_resource_guard.claim_paths(shared):
                    self.fail('A different data root bypassed the OS claim')
            with file_resource_guard.claim_paths(unrelated):
                self.assertEqual(unrelated.read_text(encoding='utf-8'), 'other')
            self.assertEqual(shared.read_text(encoding='utf-8'), 'original')
        finally:
            self.close_holder(child)
        with file_resource_guard.claim_paths(shared):
            self.assertEqual(shared.read_text(encoding='utf-8'), 'original')

    def test_shared_claim_directory_symlink_is_rejected(self):
        root = file_resource_guard._FILE_EFFECT_CLAIM_ROOT
        destination = self.base / 'attacker-controlled'
        destination.mkdir()
        try:
            root.symlink_to(destination, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Directory symlinks unavailable')
        target = self.folder / 'safe.txt'
        target.write_text('safe', encoding='utf-8')
        with self.assertRaises(file_resource_guard.resource_leases.LeaseConflict):
            with file_resource_guard.claim_paths(target):
                self.fail('Claim directory symlink should fail closed')
        self.assertEqual(target.read_text(encoding='utf-8'), 'safe')

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

    def test_undo_cannot_reverse_file_while_another_worker_owns_it(self):
        changed = self.folder / 'changed.txt'
        original = self.folder / 'original.txt'
        changed.write_text('unchanged', encoding='utf-8')
        file_ops._record([[str(changed), str(original), file_ops._digest(changed)]], 'alice')
        child = self.holder(changed)
        try:
            result = file_ops.undo('alice')
            self.assertIn('geri alamadım', result)
            self.assertTrue(changed.exists())
            self.assertFalse(original.exists())
        finally:
            self.close_holder(child)

    def test_patch_text_joins_same_resource_claim(self):
        target = self.folder / 'not.txt'
        target.write_text('before', encoding='utf-8')
        child = self.holder(target)
        try:
            with self.assertRaises(file_worker_extensions.FileWorkerExtensionError):
                file_worker_extensions.patch_text(target, {'before':'after'})
            self.assertEqual(target.read_text(encoding='utf-8'), 'before')
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

    def test_file_replaced_between_preflight_and_os_lock_is_refused(self):
        source = self.folder / 'to-change.txt'
        source.write_text('old identity', encoding='utf-8')
        original = file_resource_guard.resource_leases.process_resource_claim
        changed = False

        @contextmanager
        def swap_before_yield(root, key):
            nonlocal changed
            with original(root, key):
                if not changed:
                    changed = True
                    replacement = self.folder / 'replacement.tmp'
                    replacement.write_text('new identity', encoding='utf-8')
                    os.replace(replacement, source)
                yield

        with patch.object(file_resource_guard.resource_leases,
                          'process_resource_claim', side_effect=swap_before_yield):
            with self.assertRaises(file_resource_guard.resource_leases.LeaseConflict):
                with file_resource_guard.claim_paths(source):
                    self.fail('Worker must not act on a replaced path')
        self.assertEqual(source.read_text(encoding='utf-8'), 'new identity')

    def test_hardlink_alias_is_fenced_by_existing_file_identity(self):
        original = self.folder / 'original-hardlink.txt'
        alias = self.folder / 'alias-hardlink.txt'
        original.write_text('same object', encoding='utf-8')
        try:
            os.link(original, alias)
        except OSError:
            self.skipTest('Hardlinks not supported')
        if not original.stat().st_ino:
            self.skipTest('Filesystem did not expose a unique inode')
        child = self.holder(original)
        try:
            with self.assertRaises(file_resource_guard.resource_leases.LeaseConflict):
                with file_resource_guard.claim_paths(alias):
                    self.fail('Hardlink alias bypassed the claim')
        finally:
            self.close_holder(child)

    def test_chosen_collision_suffix_is_reserved_before_create(self):
        occupied = self.folder / 'note.txt'
        occupied.write_text('existing', encoding='utf-8')
        chosen = self.folder / 'note (1).txt'
        child = self.holder(chosen)
        try:
            with patch.object(file_ops.files, 'match_folder',
                              return_value=(self.folder, 'Belgeler', False)):
                message = file_ops.execute_typed(
                    'create', owner='alice', folder='belgeler',
                    name='note.txt', content='new',
                )
            self.assertIn('başka bir işlem', message)
            self.assertFalse(chosen.exists())
            self.assertEqual(occupied.read_text(encoding='utf-8'), 'existing')
        finally:
            self.close_holder(child)

    def test_chosen_collision_suffix_is_reserved_before_move(self):
        source_folder = self.base / 'Downloads'
        source_folder.mkdir()
        source = source_folder / 'report.txt'
        source.write_text('new report', encoding='utf-8')
        (self.folder / 'report.txt').write_text('existing', encoding='utf-8')
        chosen = self.folder / 'report (1).txt'
        child = self.holder(chosen)
        try:
            with patch.object(file_ops.files, 'match_folder',
                              return_value=(self.folder, 'Belgeler', False)), \
                 patch.object(file_ops, '_roots',
                              return_value=[source_folder, self.folder]):
                message = file_ops.execute_typed(
                    'move', owner='alice', path=str(source), folder='belgeler',
                )
            self.assertIn('başka bir işlem', message)
            self.assertTrue(source.exists())
            self.assertFalse(chosen.exists())
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
