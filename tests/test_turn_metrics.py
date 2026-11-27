"""Tur ölçümü: süre ve sonuç kaydedilir, mesaj metni yazılmaz, ölçüm hatası turu bozmaz."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import turn_metrics


class TurnMetricsTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for target, name, value in (
            (turn_metrics, '_dir', lambda: self.dir),
            (turn_metrics, '_STARTS', {}),
            (turn_metrics, '_LAST_PARTIAL', {}),
        ):
            p = patch.object(target, name, value) if not callable(value) else patch.object(target, name, value)
            p.start(); self.addCleanup(p.stop)

    def rows(self, owner='alice'):
        path = self.dir / (owner + '.jsonl')
        return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_a_finished_turn_records_duration_and_no_text(self):
        turn_metrics.start('rid-1', 'alice', 'yazı')
        with patch.object(turn_metrics.time, 'monotonic', side_effect=[100.0, 104.25]):
            turn_metrics.start('rid-2', 'alice', 'yazı')
            turn_metrics.finish('rid-2', 'ok')
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ms'], 4250)
        self.assertEqual(rows[0]['src'], 'yazı')
        self.assertEqual(rows[0]['r'], 'ok')
        self.assertNotIn('text', rows[0])

    def test_finish_without_start_writes_nothing(self):
        turn_metrics.finish('hiç-başlamamış', 'ok')
        self.assertEqual(self.rows(), [])

    def test_same_request_id_keeps_the_first_start(self):
        with patch.object(turn_metrics.time, 'monotonic', side_effect=[10.0, 12.0]):
            turn_metrics.start('rid', 'alice', 'yazı')
            turn_metrics.start('rid', 'alice', 'ses')
            turn_metrics.finish('rid', 'ok')
        row = self.rows()[0]
        self.assertEqual(row['ms'], 2000)
        self.assertEqual(row['src'], 'yazı')

    def test_summary_counts_sources_outcomes_and_durations(self):
        for rid, source, outcome, seconds in (('a', 'yazı', 'ok', 2), ('b', 'ses', 'ok', 4), ('c', 'yazı', 'iptal', 6)):
            with patch.object(turn_metrics.time, 'monotonic', side_effect=[0.0, float(seconds)]):
                turn_metrics.start(rid, 'alice', source)
                turn_metrics.finish(rid, outcome)
        text = turn_metrics.summary('alice')
        self.assertIn('3 tur', text)
        self.assertIn('ortalama 4,0 sn', text)
        self.assertIn('en uzun 6,0 sn', text)
        self.assertIn('yazı 2 tur', text)
        self.assertIn('2 cevap', text)
        self.assertIn('1 iptal', text)
        self.assertIn('sesin duyulduğu an değildir', text)

    def test_empty_day_says_so_instead_of_inventing_a_number(self):
        text = turn_metrics.summary('alice')
        self.assertIn('kayıtlı tur yok', text)

    def test_a_broken_line_is_reported_as_partial(self):
        path = self.dir / 'alice.jsonl'
        path.write_text('{"t": "2026-11-28T10:00:00+03:00", "ms": 1000, "src": "yazı", "r": "ok"}\n{bozuk\n',
                        encoding='utf-8')
        text = turn_metrics.summary('alice', '2026-11-28')
        self.assertIn('1 tur', text)
        self.assertIn('Ölçüm kısmi', text)

    def test_records_for_other_days_are_not_counted(self):
        path = self.dir / 'alice.jsonl'
        path.write_text('{"t": "2026-11-27T10:00:00+03:00", "ms": 1000, "src": "yazı", "r": "ok"}\n', encoding='utf-8')
        self.assertEqual(turn_metrics.rows('alice', '2026-11-28'), [])

    def test_rotation_archives_the_full_file(self):
        path = self.dir / 'alice.jsonl'
        path.write_text('x' * 50, encoding='utf-8')
        with patch.object(turn_metrics, '_MAX_BYTES', 10):
            turn_metrics.record({'t': '2026-11-28T10:00:00+03:00', 'ms': 5, 'src': 'yazı', 'r': 'ok'}, 'alice')
        self.assertTrue(list(self.dir.glob('alice.jsonl.archive-*')))
        self.assertEqual(len(self.rows()), 1)

    def test_command_answers_without_reaching_the_model(self):
        self.assertIn('kayıtlı tur yok', turn_metrics.handle('alice', 'Jarvis, bugün kaç tur?'))
        self.assertIn('kayıtlı tur yok', turn_metrics.handle('alice', 'TUR ÖLÇÜMÜ.'))
        self.assertIsNone(turn_metrics.handle('alice', 'bugün hava nasıl'))


if __name__ == '__main__':
    unittest.main()
