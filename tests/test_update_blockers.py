"""Güncellemeyi engelleyen yerel farklar: kaynak dışı çıktılar karşılaştırılmaz, gerçek değişiklikler korunur ve listelenir."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import updater
from modules.source_sync import blob_sha

ROOT = Path(__file__).resolve().parents[1]


class UpdateBlockerTests(unittest.TestCase):
    def tree(self, root, remote):
        (root / 'main.py').write_bytes(b'x=1\n'); (root / 'web.py').write_bytes(b'y=1\n')
        return json.dumps({'tree': [{'path': p, 'type': 'blob', 'sha': blob_sha(d)} for p, d in remote.items()]}).encode()

    def test_acceptance_report_and_temp_files_are_not_source(self):
        # Regresyon: v2_kontrol.bat kabul raporunu Jarvis köküne yazıyor; rapor güncellemeyi "local_changes" ile kilitliyordu.
        with tempfile.TemporaryDirectory() as td, patch.object(updater, 'ROOT', Path(td)):
            root = Path(td)
            raw = self.tree(root, {'main.py': b'x=1\n', 'web.py': b'y=1\n'})
            (root / 'v2_kabul_sonucu.json').write_text('{"checks": []}', encoding='utf-8')
            (root / 'v2_kabul_sonucu_ev.json').write_text('{}', encoding='utf-8')
            (root / '.v2_kontrol_gecici').mkdir(); (root / '.v2_kontrol_gecici' / 'not.txt').write_text('x', encoding='utf-8')
            (root / 'test_eki.pdf').write_bytes(b'%PDF-1.4')
            (root / 'main.py.yeni').write_text('taslak', encoding='utf-8')
            with patch.object(updater, '_get', return_value=raw):
                self.assertEqual(updater._source_changes_against('remote'), [])

    def test_real_code_changes_still_block_and_are_named(self):
        with tempfile.TemporaryDirectory() as td, patch.object(updater, 'ROOT', Path(td)):
            root = Path(td)
            raw = self.tree(root, {'main.py': b'x=1\n', 'web.py': b'y=1\n', 'modules/gone.py': b'z=1\n'})
            (root / 'main.py').write_bytes(b'x=2\n')                       # değişmiş
            (root / 'notlar.txt').write_text('kendi notum', encoding='utf-8')   # yalnız bu PC'de
            (root / 'v2_kabul_sonucu.json').write_text('{}', encoding='utf-8')  # kaynak değil
            with patch.object(updater, '_get', return_value=raw):
                changes = updater._source_changes_against('remote')
            self.assertEqual(changes, ['main.py', 'modules/gone.py', 'notlar.txt'])
            kinds = {d['path']: d['kind'] for d in updater.describe_changes(changes, 'remote')}
            self.assertEqual(kinds, {'main.py': "GitHub'dakinden farklı", 'modules/gone.py': "bu PC'de yok",
                                     'notlar.txt': "yalnız bu PC'de"})
            self.assertEqual((root / 'main.py').read_bytes(), b'x=2\n')     # hiçbir dosya ezilmez

    def test_verify_sync_message_lists_blocking_files(self):
        with tempfile.TemporaryDirectory() as td, patch.object(updater, 'ROOT', Path(td)):
            root = Path(td)
            raw = self.tree(root, {'main.py': b'x=1\n', 'web.py': b'y=1\n'})
            (root / 'notlar.txt').write_text('x', encoding='utf-8')
            with patch.object(updater, 'status', return_value={}), patch.object(updater, 'latest', return_value={'sha': 'same'}), \
                    patch.object(updater, '_state', return_value={'sha': 'same'}), patch.object(updater, '_get', return_value=raw), \
                    patch.object(updater, '_save_state') as save, patch.object(updater, 'mark_current') as mark:
                out = updater.verify_sync()
        self.assertEqual(out['sync_state'], 'local_changes')
        self.assertEqual(out['local_change_details'], [{'path': 'notlar.txt', 'kind': "yalnız bu PC'de"}])
        self.assertIn("Engelleyen dosyalar: notlar.txt (yalnız bu PC'de)", out['sync_msg'])
        self.assertIn('Engelleyen dosyalar', save.call_args.kwargs['sync_msg'])
        mark.assert_not_called()

    def test_report_alone_now_counts_as_synced(self):
        with tempfile.TemporaryDirectory() as td, patch.object(updater, 'ROOT', Path(td)):
            root = Path(td)
            raw = self.tree(root, {'main.py': b'x=1\n', 'web.py': b'y=1\n'})
            (root / 'v2_kabul_sonucu.json').write_text('{}', encoding='utf-8')
            with patch.object(updater, 'status', return_value={}), patch.object(updater, 'latest', return_value={'sha': 'same'}), \
                    patch.object(updater, '_state', return_value={'sha': 'same'}), patch.object(updater, '_get', return_value=raw), \
                    patch.object(updater, '_save_state'), patch.object(updater, 'mark_current'):
                self.assertEqual(updater.verify_sync()['sync_state'], 'synced')

    def test_gitignored_outputs_are_never_publishable(self):
        # .gitignore'daki her kalıp için örnek bir yol, yayın/karşılaştırma kapsamına girmemeli.
        for line in (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines():
            pat = line.strip()
            if not pat or pat.startswith(('#', '!')):
                continue
            sample = pat.rstrip('/').replace('*', 'x').replace('[cod]', 'c')
            for path in (sample, sample + '/a.json') if pat.endswith('/') or '.' not in Path(sample).name else (sample,):
                self.assertFalse(updater._publishable_path(path), f'{pat} → {path}')

    def test_publish_never_uploads_local_reports(self):
        from modules import git_publish
        with tempfile.TemporaryDirectory() as td, patch.object(git_publish, 'ROOT', Path(td)):
            root = Path(td)
            (root / 'main.py').write_bytes(b'x=1\n')
            (root / 'v2_kabul_sonucu.json').write_text('{}', encoding='utf-8')
            (root / '.v2_kontrol_gecici').mkdir(); (root / '.v2_kontrol_gecici' / 'a.json').write_text('{}', encoding='utf-8')
            self.assertEqual(set(git_publish._publishable_files()), {'main.py'})

    def test_acceptance_detail_names_files(self):
        from modules import acceptance_checks
        status = {'sync_state': 'local_changes', 'local_change_details': [{'path': 'main.py', 'kind': "GitHub'dakinden farklı"}]}
        with patch.object(updater, 'verify_sync', return_value=status), \
                patch('modules.service_health.report', return_value='ok'):
            report = acceptance_checks.run(suite=False)
        row = next(r for r in report['checks'] if r['check'] == 'github_source')
        self.assertEqual(row['state'], 'pending')
        self.assertEqual(row['detail'], "local_changes: main.py (GitHub'dakinden farklı)")


if __name__ == '__main__':
    unittest.main()
