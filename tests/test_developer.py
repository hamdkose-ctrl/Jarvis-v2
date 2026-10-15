"""No live model: actual files, persistent drafts, revisions and transactions."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from modules import developer as dev, history

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200"><rect width="400" height="200" fill="#123"/><text x="30" y="90" fill="white">Jarvis</text></svg>'


class DeveloperTests(unittest.TestCase):
    def test_failed_candidate_can_be_repaired_and_retested_without_applying(self):
        self.enable()
        calls = [
            {'tool': 'read', 'path': 'example.py'},
            {'tool': 'edit', 'path': 'example.py', 'old': 'value = 1', 'new': 'value = 2'},
            {'tool': 'test'},
            {'tool': 'edit', 'path': 'example.py', 'old': 'value = 2', 'new': 'value = 3'},
            {'tool': 'test'},
            {'tool': 'finish', 'message': 'Taslak hazır.'}]
        with patch.object(dev, '_test', side_effect=[(False, 'FAIL: wrong value'), (True, 'OK')]) as checks:
            reply = self.model_turn(*calls)
        self.assertEqual(checks.call_count, 2)
        self.assertIn('FAIL: wrong value', self.ask.call_args.args[0])
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertEqual(self.state()['draft']['example.py']['content'], 'value = 3\n')
        self.assertIn('Taslak testleri geçti', reply)
        self.assertIn('Kaynaklara uygulanmadı', reply)

    def test_draft_test_evidence_expires_on_edit_and_source_conflict(self):
        self.stage()
        state = self.state()
        with patch.object(dev, '_test', return_value=(True, 'OK')):
            self.assertTrue(dev._test_draft('alice', state)['ok'])
        dev._stage(state, 'example.py', 'value = 3\n')
        self.assertIn('henüz test edilmedi', dev._draft_status(state))
        self.source.write_text('value = 99\n')
        with patch.object(dev, '_test') as checks:
            self.assertFalse(dev._test_draft('alice', state)['ok'])
        checks.assert_not_called()

    def test_locked_development_cannot_run_candidate_tests(self):
        self.stage()
        dev._AUTH.clear()
        with patch.object(dev, '_test') as checks:
            for command in ('geliştirmeyi test et', 'taslağı test et'):
                self.assertIn('kilitli', dev.handle('alice', command))
        checks.assert_not_called()

    def test_svg_without_namespace_is_normalized_for_browser_image(self):
        state = dev._load('alice')
        item = dev._visual('alice', state, 'Tasarım', '<svg viewBox="0 0 200 100"><defs><linearGradient id="g"><stop offset="0" stop-color="#123"/></linearGradient></defs><rect width="200" height="100" fill="url(#g)"/></svg>')
        root = ET.fromstring(item['svg'])
        self.assertTrue(all(el.tag.startswith('{http://www.w3.org/2000/svg}') for el in root.iter()))
        self.assertEqual(root.find('{http://www.w3.org/2000/svg}rect').get('fill'), 'url(#g)')
        payload = dev._image_markdown(item).split('base64,', 1)[1].rstrip(')')
        self.assertEqual(ET.fromstring(base64.b64decode(payload)).tag, '{http://www.w3.org/2000/svg}svg')

    def test_old_saved_svg_preview_is_normalized_without_rewriting_source(self):
        item = {'title':'Eski', 'svg':'<svg viewBox="0 0 10 10"><circle r="3"/></svg>'}
        before = item['svg']
        payload = dev._image_markdown(item).split('base64,', 1)[1].rstrip(')')
        self.assertEqual(ET.fromstring(base64.b64decode(payload)).tag, '{http://www.w3.org/2000/svg}svg')
        self.assertEqual(item['svg'], before)

    def test_foreign_namespace_and_invalid_saved_svg_are_not_rendered(self):
        with self.assertRaises(ValueError):
            dev._svg_bytes('<svg xmlns="http://www.w3.org/1999/xhtml"/>')
        self.assertIn('önizleme açılamadı', dev._image_markdown({'title':'Bozuk', 'svg':'<svg>'}))

    def test_model_image_links_cannot_replace_registered_visuals(self):
        self.enable()
        result = self.model_turn({'tool':'visual', 'title':'Gerçek', 'svg':SVG},
            {'tool':'finish', 'message':'Örnek: ![Uydurma](https://example.invalid/missing.svg) ![Bozuk](data:image/svg+xml;base64,PHN2Zz4=)'})
        self.assertNotIn('example.invalid', result)
        self.assertEqual(result.count('data:image/svg+xml;base64,'), 1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'; self.root.mkdir()
        for attr, value in [('PROJECT', self.root), ('STORE', Path(self.tmp.name) / 'state')]:
            p = patch.object(dev, attr, value); p.start(); self.addCleanup(p.stop)
        auth = patch.object(dev, '_AUTH', set()); auth.start(); self.addCleanup(auth.stop)
        dev.unlock('alice', 'test-pass')
        self.source = self.root / 'example.py'; self.source.write_bytes(b'value = 1\n')
        self.model = patch.object(dev.llm, 'ask'); self.ask = self.model.start(); self.addCleanup(self.model.stop)

    def enable(self, owner='alice'):
        return dev.enable(owner)

    def state(self):
        return dev._load('alice')

    def stage(self, content='value = 2\n'):
        self.enable(); state = self.state(); dev._stage(state, 'example.py', content); dev._save('alice', state)

    def test_draft_path_alias_replaces_same_entry_and_preserves_original_base(self):
        state = self.state()
        dev._stage(state, 'example.py', 'value = 2\n')
        original = state['draft']['example.py']['base']
        dev._stage(state, './example.py', 'value = 3\n')
        self.assertEqual(list(state['draft']), ['example.py'])
        self.assertEqual(state['draft']['example.py']['base'], original)
        self.assertEqual(dev._read(state, './example.py'), 'value = 3\n')
        self.assertEqual(self.source.read_text(), 'value = 1\n')

    def test_old_duplicate_draft_paths_are_rejected_before_tests_or_writes(self):
        for alias in ('./example.py', 'Example.py'):
            with self.subTest(alias=alias):
                state = self.state()
                dev._stage(state, 'example.py', 'value = 2\n')
                state['draft'][alias] = dict(state['draft']['example.py'], content='value = 3\n')
                with patch.object(dev, '_test') as checks, patch.object(dev, '_atomic') as write:
                    result = dev._apply('alice', state)
                self.assertIn('birden fazla', result)
                checks.assert_not_called();write.assert_not_called()
                self.assertEqual(self.source.read_text(), 'value = 1\n')

    def test_asset_alias_uses_same_draft_entry(self):
        state = self.state()
        ref = dev._folder('alice') / 'references' / 'image.png'
        ref.parent.mkdir();ref.write_bytes(b'image-bytes')
        state['references'].append({'id': 'image', 'kind': 'image', 'name': 'image.png'})
        dev._stage_asset('alice', state, 'logo.png', 'image')
        dev._stage_asset('alice', state, './logo.png', 'image')
        self.assertEqual(list(state['draft']), ['logo.png'])
        self.assertIn('11 bayt', dev._read(state, './logo.png'))

    def model_turn(self, *calls):
        # Candidate tests may ask the model to revise a failed draft before finishing.
        replies = list(calls) + ([calls[-1]] * 3 if calls and calls[-1].get('tool') == 'finish' else [])
        self.ask.side_effect = [json.dumps(c, ensure_ascii=False) for c in replies]
        return dev.handle('alice', 'şu hatayı düzelt')

    def test_task_worker_can_receive_model_failure_instead_of_success_message(self):
        self.enable();self.ask.side_effect=RuntimeError('model offline')
        with self.assertRaises(RuntimeError):dev.handle('alice','hatayı düzelt',raise_errors=True)
        self.assertTrue(dev.status('alice')['enabled'])

    def test_code_job_retries_text_only_finish_and_explains_missing_file(self):
        self.enable()
        self.ask.side_effect=[json.dumps({'tool':'finish','message':'Yalnız açıklama verdim.'})]*3
        result=dev.handle('alice','Kod örneği üret',raise_errors=True,require_draft=True)
        self.assertEqual(self.ask.call_count,3)
        self.assertIn('dosya taslağı oluşturmadı',result)
        self.assertFalse(dev.status('alice')['draft_files'])
        self.assertEqual(self.source.read_text(),'value = 1\n')

    def test_code_job_can_recover_from_text_only_finish_and_stage_without_apply(self):
        self.enable()
        calls=[{'tool':'finish','message':'Metin açıklaması'}, {'tool':'read','path':'example.py'},
               {'tool':'stage','path':'example.py','content':'value = 2\n'},
               {'tool':'read','path':'test_example.py'},
               {'tool':'stage','path':'test_example.py','content':'import unittest\nfrom example import value\nclass Tests(unittest.TestCase):\n def test_value(self): self.assertEqual(value, 2)\n'},
               {'tool':'test'}, {'tool':'finish','message':'Taslak hazır.'}]
        self.ask.side_effect=[json.dumps(c) for c in calls]
        with patch.object(dev,'_test',return_value=(True,'test passed')):
            result=dev.handle('alice','Kod taslağı üret',require_draft=True,raise_errors=True)
        self.assertIn('Taslak hazır',result)
        self.assertTrue(dev.status('alice')['draft_test_ok'])
        self.assertEqual(self.source.read_text(),'value = 1\n')

    def test_normal_chat_is_untouched_and_enable_does_not_call_model(self):
        self.assertIsNone(dev.handle('alice', 'merhaba'))
        self.enable(); self.ask.assert_not_called()
        self.assertTrue(dev.status('alice')['enabled'])

    def test_stage_from_real_read_changes_nothing_until_explicit_apply(self):
        self.enable()
        result = self.model_turn({'tool': 'read', 'path': 'example.py'}, {'tool': 'edit', 'path': 'example.py', 'old': 'value = 1', 'new': 'value = 2'}, {'tool': 'finish', 'message': 'Düzelttim: taslak hazır.'})
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertIn('```diff', result)
        self.assertEqual(self.state()['draft']['example.py']['content'], 'value = 2\n')
        self.assertIn('şu hatayı düzelt', self.ask.call_args.args[0])

    def test_restart_and_user_separation_preserve_context(self):
        self.enable(); self.model_turn({'tool': 'finish', 'message': 'Mavi tasarım.'})
        self.ask.side_effect = [json.dumps({'tool': 'finish', 'message': 'Devam.'})]
        dev.handle('alice', 'bunu değiştir')
        self.assertIn('Mavi tasarım.', self.ask.call_args.args[0])
        self.assertIsNone(dev.handle('bob', 'bunu değiştir'))
        dev.handle('alice', 'normal sohbete dön'); dev.unlock('alice', 'test-pass'); self.enable()
        self.assertEqual(self.state()['turns'][0]['text'], 'şu hatayı düzelt')

    def test_revision_reads_pending_draft_and_keeps_original_conflict_hash(self):
        self.stage(); before = self.state()['draft']['example.py']['base']
        self.model_turn({'tool': 'read', 'path': 'example.py'}, {'tool': 'edit', 'path': 'example.py', 'old': 'value = 2', 'new': 'value = 3'}, {'tool': 'finish', 'message': 'Revize.'})
        self.assertIn('value = 2', self.ask.call_args.args[0])
        self.assertEqual(self.state()['draft']['example.py']['base'], before)
        self.assertEqual(self.state()['draft']['example.py']['content'], 'value = 3\n')

    def test_model_cannot_apply_or_write_without_reading(self):
        self.enable()
        self.model_turn({'tool': 'apply'}, {'tool': 'stage', 'path': 'example.py', 'content': 'value = 3'}, {'tool': 'finish', 'message': 'Bitti.'})
        self.assertEqual(self.state()['draft'], {})
        self.assertEqual(self.source.read_text(), 'value = 1\n')

    def test_ambiguous_edit_and_invalid_python_are_rejected(self):
        self.source.write_text('a = 1\nb = 1\n'); self.enable()
        self.model_turn({'tool': 'read', 'path': 'example.py'}, {'tool': 'edit', 'path': 'example.py', 'old': ' = 1', 'new': ' = 2'}, {'tool': 'stage', 'path': 'example.py', 'content': 'def broken('}, {'tool': 'finish', 'message': 'Hazır değil.'})
        self.assertEqual(self.state()['draft'], {})

    def test_conflict_prevents_all_writes_and_tests(self):
        self.stage(); self.source.write_text('value = 99\n')
        with patch.object(dev, '_test') as test:
            result = dev.handle('alice', 'değişiklikleri uygula')
        test.assert_not_called(); self.assertIn('değişmiş', result)
        self.assertEqual(self.source.read_text(), 'value = 99\n')

    def test_successful_apply_records_backup_and_can_undo(self):
        self.stage()
        with patch.object(dev, '_test', return_value=(True, 'Ran 10 tests: OK')) as test:
            result = dev.handle('alice', 'değişiklikleri uygula')
        test.assert_called_once(); self.assertIn('uygulandı', result)
        self.assertEqual(self.source.read_text(), 'value = 2\n')
        self.assertEqual(self.state()['draft'], {})
        dev.handle('alice', 'son geliştirmeyi geri al')
        self.assertEqual(self.source.read_text(), 'value = 1\n')

    def test_test_failure_rolls_back_existing_added_and_deleted_files(self):
        self.stage(); state = self.state()
        dev._stage(state, 'new.py', 'created = True\n')
        old = self.root / 'old.txt'; old.write_bytes(b'old\r\n')
        dev._stage(state, 'old.txt', None); dev._save('alice', state)
        with patch.object(dev, '_test', return_value=(False, 'FAIL: regression')):
            result = dev.handle('alice', 'değişiklikleri uygula')
        self.assertIn('değiştirilmedi', result)
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertFalse((self.root / 'new.py').exists())
        self.assertEqual(old.read_bytes(), b'old\r\n')
        self.assertEqual(len(self.state()['draft']), 3)

    def test_timeout_rolls_back(self):
        self.stage()
        with patch.object(dev, '_test', side_effect=TimeoutError('test timeout')):
            result = dev.handle('alice', 'değişiklikleri uygula')
        self.assertIn('değiştirilmedi', result)
        self.assertEqual(self.source.read_text(), 'value = 1\n')

    def test_undo_refuses_to_overwrite_later_edits(self):
        self.stage()
        with patch.object(dev, '_test', return_value=(True, 'OK')):
            dev.handle('alice', 'değişiklikleri uygula')
        self.source.write_text('value = 77\n')
        with self.assertRaisesRegex(ValueError, 'sonradan değişmiş'):
            dev.handle('alice', 'son geliştirmeyi geri al')
        self.assertEqual(self.source.read_text(), 'value = 77\n')

    def test_interrupted_apply_is_recovered_on_restart(self):
        self.stage()
        records = {'example.py': {'before': base64.b64encode(self.source.read_bytes()).decode(), 'after': dev._hash(b'value = 2\n')}}
        dev._atomic(dev._folder('alice') / 'backup.json', json.dumps({'status': 'applying', 'files': records}).encode())
        self.source.write_bytes(b'value = 2\n'); self.enable()
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertTrue(self.state()['draft'])

    def test_paths_and_symlinks_cannot_escape_project(self):
        for name in ('../else.py', '/tmp/else.py', '.git/config', '.env', 'keys/secret.txt', 'image.exe', 'C:\\other.py'):
            with self.assertRaises(ValueError): dev._path(name)

    def test_symlink_cannot_escape_project(self):
        outside = Path(self.tmp.name) / 'outside.py'; outside.write_text('secret')
        try:
            (self.root / 'link.py').symlink_to(outside)
        except OSError:
            self.skipTest('Bu ortam sembolik bağlantı oluşturamıyor')
        with self.assertRaises(ValueError): dev._path('link.py')

    def test_model_failure_keeps_request_and_never_echoes_secret(self):
        self.enable(); self.ask.side_effect = RuntimeError('secret-key-raw')
        result = dev.handle('alice', 'önceki tasarımı büyüt')
        self.assertNotIn('secret-key-raw', result)
        self.assertEqual(self.state()['turns'][-1]['text'], 'önceki tasarımı büyüt')

    def test_visual_file_history_and_followup_survive_reload(self):
        self.enable()
        result = self.model_turn({'tool': 'visual', 'title': 'Jarvis tasarım', 'svg': SVG}, {'tool': 'finish', 'message': 'Tasarım burada.'})
        self.assertIn('data:image/svg+xml;base64,', result)
        item = self.state()['visuals'][-1]
        self.assertTrue((dev._folder('alice') / 'visuals' / (item['id'] + '.svg')).is_file())
        with patch.object(history, 'DIR', Path(self.tmp.name) / 'history'):
            history.append('alice', 'assistant', result)
            self.assertEqual(history.read('alice')[0]['text'], result)
        self.assertEqual(len(self.state()['visuals']), 1)
        self.assertIn('data:image/svg+xml;base64,', dev.handle('alice', 'son görseli göster'))
        self.ask.side_effect = [json.dumps({'tool': 'finish', 'message': 'Gördüm.'})]
        dev.handle('alice', 'görseldeki yazıyı değiştir')
        self.assertIn('viewBox', self.ask.call_args.args[0])

    def test_active_or_remote_svg_is_rejected(self):
        state = dev._load('alice')
        for svg in ('<svg><script>alert(1)</script></svg>', '<svg onload="alert(1)"/>', '<svg><image href="https://remote/a"/></svg>', '<svg><rect fill="url(https://remote/a)"/></svg>', '<svg><foreignObject/></svg>'):
            with self.assertRaises(ValueError): dev._visual('alice', state, 'Bad', svg)
        self.assertFalse(state['visuals'])

    def test_cancel_draft_and_microphone_passthrough_do_not_call_model(self):
        self.stage(); dev.handle('alice', 'taslağı iptal et')
        self.assertFalse(self.state()['draft'])
        self.assertIsNone(dev.handle('alice', 'mikrofonu kapat'))
        self.ask.assert_not_called()

    def test_password_hash_restart_lock_and_per_user_access(self):
        self.enable()
        access = (dev._folder('alice') / 'access.json').read_text()
        self.assertNotIn('test-pass', access)
        dev._AUTH.clear()
        self.assertFalse(dev.unlock('alice', 'wrong-pass')['ok'])
        self.assertIn('kilitli', dev.handle('alice', 'değişiklikleri uygula'))
        self.ask.assert_not_called()
        self.assertTrue(dev.unlock('alice', 'test-pass')['ok'])
        self.assertNotIn('bob', dev._AUTH)
        self.assertTrue(dev.change_password('alice', 'test-pass', 'new-password')['ok'])
        dev._AUTH.clear()
        self.assertFalse(dev.unlock('alice', 'test-pass')['ok'])
        self.assertTrue(dev.unlock('alice', 'new-password')['ok'])

    def test_visual_reference_is_copied_analyzed_and_kept_after_original_removed(self):
        from PIL import Image
        image = Path(self.tmp.name) / 'reference.png'; Image.new('RGB', (32, 32), 'blue').save(image)
        self.enable()
        with patch('modules.nxapi.allowed', side_effect=lambda p: Path(p)), patch.object(dev.llm, 'ask_image', return_value='Mavi pencere, sağda menü.') as vision:
            self.ask.side_effect = [json.dumps({'tool': 'finish', 'message': 'Referansı gördüm.'})]
            result = dev.handle('alice', '"' + str(image) + '" bu tasarımı yap')
        self.assertIn('data:image/png;base64,', result)
        vision.assert_called_once()
        self.assertIn('Mavi pencere', self.ask.call_args.args[0])
        image.unlink()
        ref = self.state()['references'][-1]
        self.assertTrue((dev._folder('alice') / 'references' / (ref['id'] + '.png')).is_file())

    def test_document_reference_is_read_and_redacted(self):
        source = Path(self.tmp.name) / 'spec.txt'; source.write_text('Özellik: büyük menü. sk-' + 'x' * 32)
        self.enable(); self.ask.side_effect = [json.dumps({'tool': 'finish', 'message': 'Belgeyi gördüm.'})]
        with patch('modules.nxapi.allowed', side_effect=lambda p: Path(p)):
            dev.handle('alice', '"' + str(source) + '" bunu uygula')
        self.assertIn('büyük menü', self.ask.call_args.args[0])
        self.assertNotIn('sk-' + 'x' * 32, self.ask.call_args.args[0])

    def test_auto_apply_is_disabled_even_for_legacy_saved_permission(self):
        self.enable()
        state = self.state(); state['auto_apply'] = True; dev._save('alice', state)
        self.assertFalse(self.state()['auto_apply'])
        result = dev.handle('alice', 'otomatik geliştirmeyi aç')
        self.assertIn('kaldırıldı', result)
        with patch.object(dev, '_test', return_value=(True, 'candidate OK')) as test:
            self.model_turn({'tool': 'read', 'path': 'example.py'}, {'tool': 'edit', 'path': 'example.py', 'old': 'value = 1', 'new': 'value = 2'}, {'tool': 'finish', 'message': 'Tamam.'})
        test.assert_called_once()
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertTrue(self.state()['draft'])
        with patch.object(dev, '_test', return_value=(True, 'OK')):
            dev.handle('alice', 'değişiklikleri uygula')
        self.assertEqual(self.source.read_text(), 'value = 2\n')

    def test_project_memory_and_old_conversation_are_retrievable(self):
        self.enable()
        self.model_turn({'tool': 'finish', 'message': 'Turkuaz menü.', 'memory': 'Karar: menü turkuaz, kartlar büyük.'})
        state = self.state(); state['turns'] = []; dev._save('alice', state)
        self.model_turn({'tool': 'history', 'query': 'Turkuaz'}, {'tool': 'finish', 'message': 'Eski kararı buldum.'})
        self.assertIn('kartlar büyük', self.ask.call_args.args[0])
        self.assertIn('Turkuaz menü.', self.ask.call_args.args[0])

    def test_older_visuals_remain_accessible_beyond_recent_context(self):
        self.enable(); state = self.state()
        oldest = dev._visual('alice', state, 'İlk tasarım', SVG)
        for i in range(9): dev._visual('alice', state, str(i), SVG)
        dev._save('alice', state)
        self.assertEqual(len(state['visuals']), 8)
        self.assertEqual(len(dev._all_visuals('alice')), 10)
        result = self.model_turn({'tool': 'show_visual', 'id': oldest['id']}, {'tool': 'finish', 'message': 'İlk tasarım burada.'})
        self.assertIn('data:image/svg+xml;base64,', result)
        self.assertIn(oldest['id'], self.ask.call_args.args[0])

    def test_partial_write_failure_restores_original_files(self):
        self.stage(); state = self.state(); dev._stage(state, 'new.py', 'x = 2\n'); dev._save('alice', state)
        real_atomic = dev._atomic
        def fail_new(path, data):
            if path == self.root / 'new.py': raise OSError('disk full')
            return real_atomic(path, data)
        with patch.object(dev, '_atomic', side_effect=fail_new), patch.object(dev, '_test', return_value=(True, 'OK')) as test:
            result = dev.handle('alice', 'değişiklikleri uygula')
        self.assertIn('geri aldım', result); test.assert_called_once()
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertFalse((self.root / 'new.py').exists())

    def test_failed_commit_persistence_rolls_back_applied_code(self):
        self.stage(); real_save = dev._save; fail = [True]
        def save(owner, state):
            if not state['draft'] and fail[0]:
                fail[0] = False
                raise OSError('commit failed')
            return real_save(owner, state)
        with patch.object(dev, '_save', side_effect=save), patch.object(dev, '_test', return_value=(True, 'OK')):
            result = dev.handle('alice', 'değişiklikleri uygula')
        self.assertIn('geri aldım', result)
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertTrue(self.state()['draft'])

    def test_export_contains_drafts_and_visuals_without_access_credentials(self):
        self.stage(); state = self.state(); dev._visual('alice', state, 'Tasarım', SVG); dev._save('alice', state)
        with patch('modules.nxapi.FILES_DIR', Path(self.tmp.name) / 'exports'):
            result = dev.export('alice')
        destination = Path(result['path'])
        self.assertEqual((destination / 'Taslak' / 'example.py').read_text(), 'value = 2\n')
        self.assertEqual(len(list((destination / 'Görseller').glob('*.svg'))), 1)
        self.assertFalse(list(destination.rglob('access.json')))
        with self.assertRaises(ValueError): dev.export('bob')


if __name__ == '__main__':
    unittest.main()
