"""Rotation must preserve daily counts and an interrupted write must preserve committed rows."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from modules import usage_meter as meter


class UsageMeterRotationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        directory = patch.object(meter, '_dir', return_value=self.root)
        directory.start()
        self.addCleanup(directory.stop)
        self.path = self.root / 'hamdi.jsonl'

    def record(self, chars=7, owner='hamdi'):
        meter.record('gemini', 'test', chars, 3, source='test.call', owner=owner)

    def test_multiple_rotations_keep_the_entire_daily_total(self):
        with patch.object(meter, '_MAX_BYTES', 1):
            for _ in range(7):
                self.record()
        self.assertEqual(len(meter.rows('hamdi')), 7)
        self.assertIn('toplam 7 çağrı', meter.summary('hamdi'))
        self.assertIn('49 karakter', meter.summary('hamdi'))

    def test_interrupted_replace_keeps_previously_committed_bytes(self):
        self.record()
        previous = self.path.read_bytes()
        with patch.object(os, 'replace', side_effect=OSError('interrupted replace')):
            self.record(99)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(len(meter.rows('hamdi')), 1)

    def test_fsync_failure_does_not_publish_half_written_file(self):
        self.record()
        previous = self.path.read_bytes()
        with patch.object(os, 'fsync', side_effect=OSError('disk full')):
            self.record(99)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(len(meter.rows('hamdi')), 1)

    def test_legacy_torn_tail_does_not_swallow_the_next_record(self):
        self.record()
        with self.path.open('ab') as stream:
            stream.write(b'{"t":')
        self.record()
        self.assertEqual(len(meter.rows('hamdi')), 2)
        self.assertIn('kısmi', meter.summary('hamdi').lower())

    def test_failure_after_rotation_preserves_the_archived_rows(self):
        self.record()
        replace = os.replace

        def interrupted(source, target):
            if Path(target) == self.path:
                raise OSError('interrupted new active file')
            return replace(source, target)

        with patch.object(meter, '_MAX_BYTES', 1), patch.object(os, 'replace', side_effect=interrupted):
            self.record(99)
        self.assertEqual(len(meter.rows('hamdi')), 1)
        self.record()
        self.assertEqual(len(meter.rows('hamdi')), 2)

    def test_legacy_backup_and_users_remain_separate(self):
        self.record()
        self.path.replace(self.path.with_suffix('.jsonl.1'))
        self.record()
        self.record(owner='ebru')
        self.assertEqual(len(meter.rows('hamdi')), 2)
        self.assertEqual(len(meter.rows('ebru')), 1)

    def test_legacy_backup_warns_that_earlier_rotations_are_unknown(self):
        self.record()
        self.path.replace(self.path.with_suffix('.jsonl.1'))
        self.record()
        self.assertIn('kısmi', meter.summary('hamdi').lower())

    def test_rotated_records_are_filtered_by_day(self):
        today = datetime.now(meter._TR).date().isoformat()
        old = {'t': '2000-01-01T10:00:00+03:00', 'p': 'gemini', 'm': 'x',
               's': 'test.call', 'i': 4, 'o': 1, 'r': 'ok'}
        self.path.write_text(json.dumps(old) + '\n', encoding='utf-8')
        with patch.object(meter, '_MAX_BYTES', 1):
            for _ in range(4):
                self.record()
        self.assertEqual(len(meter.rows('hamdi', today)), 4)
        self.assertEqual(len(meter.rows('hamdi', '2000-01-01')), 1)


if __name__ == '__main__':
    unittest.main()
