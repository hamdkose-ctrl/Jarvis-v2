"""Yerel yanlış yönlendirme günlüğü; gerçek kullanıcı verisi veya servis kullanılmaz."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from modules import misroute_log as log


class MisrouteLogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'misroute_logs'
        patcher = patch.object(log, '_ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self, user='alice'):
        return json.loads((self.root / f'{user}.json').read_text(encoding='utf-8'))

    def test_users_are_isolated_and_clear_only_removes_owner(self):
        log.record('alice', 'Nedir bu?', 'goal')
        log.mark_wrong('alice', 'chat')
        self.assertEqual(log.export_candidates('bob'), [])
        log.record('bob', 'Dosyayı aç', 'chat')
        log.mark_wrong('bob', 'task')
        log.clear('alice')
        self.assertEqual(log.export_candidates('alice'), [])
        self.assertEqual(len(log.export_candidates('bob')), 1)

    def test_raw_file_redacts_all_free_text_even_when_redaction_disabled(self):
        secrets = ['sk-' + 'a' * 28, 'alice@example.org', '0532 123 45 67', '4111 1111 1111 1111']
        text = ' '.join(secrets)
        with patch('modules.privacy.redact_enabled', return_value=False):
            log.record('alice', text, 'chat', result=text, note=text)
            log.mark_wrong('alice')
        raw = (self.root / 'alice.json').read_text(encoding='utf-8')
        for secret in secrets:
            self.assertNotIn(secret, raw)
        for label in ['anahtar', 'e-posta', 'telefon', 'kart']:
            self.assertIn(f'[{label} gizlendi]', raw)
        self.assertNotIn('alice@example.org', json.dumps(log.export_candidates('alice')))

    def test_only_last_record_is_marked_and_export_uses_expected_model_label(self):
        log.record('alice', 'İlk cümle', 'chat')
        log.record('alice', 'Sohbet sorusu', 'goal', result='yanlış görev', note='kontrol et')
        log.mark_wrong('alice', 'chat')
        candidates = log.export_candidates('alice')
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['metin'], 'Sohbet sorusu')
        self.assertEqual(candidates[0]['beklenen'], 'chat')
        self.assertEqual(candidates[0]['model'], 'chat')
        self.assertEqual(candidates[0]['gerceklesen_yol'], 'goal')
        self.assertFalse(self.rows()[0]['wrong'])
        candidates[0]['metin'] = 'değişti'
        self.assertEqual(log.export_candidates('alice')[0]['metin'], 'Sohbet sorusu')

    def test_unmarked_export_is_empty_and_marking_empty_log_is_harmless(self):
        self.assertFalse(log.mark_wrong('alice'))
        log.record('alice', 'Merhaba', 'chat')
        self.assertEqual(log.export_candidates('alice'), [])

    def test_missing_expected_label_remains_for_human_review(self):
        log.record('alice', 'Bunu yap', 'smart_router')
        self.assertTrue(log.mark_wrong('alice'))
        candidate = log.export_candidates('alice')[0]
        self.assertEqual(candidate['beklenen'], '')
        self.assertEqual(candidate['model'], '')
        self.assertTrue(candidate['tartismali'])

    def test_keeps_last_500_records(self):
        for i in range(503):
            log.record('alice', f'cümle {i}', 'chat')
        rows = self.rows()
        self.assertEqual(len(rows), 500)
        self.assertEqual(rows[0]['text'], 'cümle 3')
        self.assertEqual(rows[-1]['text'], 'cümle 502')

    def test_long_fields_are_bounded_after_masking(self):
        log.record('alice', 'a' * 100_000, 'chat', result='b' * 100_000, note='c' * 100_000)
        row = self.rows()[0]
        self.assertLessEqual(len(row['text']), 4000)
        self.assertLessEqual(len(row['result']), 1000)
        self.assertLessEqual(len(row['note']), 1000)

    def test_partial_and_invalid_shape_files_are_reported_and_preserved(self):
        self.root.mkdir()
        path = self.root / 'alice.json'
        for bad in ['[{', '{}', '[{}]', '[null]']:
            with self.subTest(bad=bad):
                path.write_text(bad, encoding='utf-8')
                with patch.object(log, '_record_failure') as diagnostic:
                    with self.assertRaises(ValueError):
                        log.record('alice', 'yeni', 'chat')
                    diagnostic.assert_called_once()
                self.assertEqual(path.read_text(encoding='utf-8'), bad)

    def test_two_threads_do_not_lose_or_break_records(self):
        def write(prefix):
            for i in range(40):
                log.record('alice', f'{prefix}-{i}', 'chat')
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(write, ['bir', 'iki']))
        rows = self.rows()
        self.assertEqual(len(rows), 80)
        self.assertEqual({r['text'] for r in rows}, {f'{p}-{i}' for p in ['bir', 'iki'] for i in range(40)})

    def test_path_traversal_is_rejected_by_every_entry_point(self):
        for slug in ['../x', '..\\x', 'C:\\x', '/x', '', '.', 'Alice', 'a/b']:
            for call in [lambda: log.record(slug, 'x', 'chat'), lambda: log.mark_wrong(slug),
                         lambda: log.export_candidates(slug), lambda: log.clear(slug)]:
                with self.subTest(slug=slug), self.assertRaises(ValueError):
                    call()
        self.assertFalse(self.root.exists())

    def test_failed_atomic_replace_preserves_previous_file_and_reports_failure(self):
        log.record('alice', 'eski', 'chat')
        with patch.object(log.os, 'replace', side_effect=OSError('test')), patch.object(log, '_record_failure') as diagnostic:
            with self.assertRaises(OSError):
                log.record('alice', 'yeni', 'chat')
            diagnostic.assert_called_once()
        self.assertEqual([r['text'] for r in self.rows()], ['eski'])
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_transient_windows_replace_lock_is_retried(self):
        replace = log.os.replace
        attempts = []
        def busy_once(source, target):
            attempts.append(source)
            if len(attempts) == 1:
                raise PermissionError('Geçici dosya kilidi')
            return replace(source, target)
        with patch.object(log.os, 'replace', side_effect=busy_once):
            log.record('alice', 'yeni', 'chat')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.rows()[0]['text'], 'yeni')


if __name__ == '__main__':
    unittest.main()
