"""Full update lifecycle with real files/journals and no network or pip calls."""
import io
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import zipfile
import updater
import release_guard as guard
import launcher
from modules import release_workspace as workspace


class SafeUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'project';self.root.mkdir()
        self.data=Path(self.tmp.name)/'data';self.data.mkdir()
        self.state=self.data/'update.json';guard.save(self.state,{'sha':'old','msg':'old'})
        for name,value in {'main.py':b'old = 1\n','web.py':b'old = 1\n','deleted.txt':b'old text','logo.png':b'old image'}.items():
            (self.root/name).write_bytes(value)
        self.info={'sha':'new','msg':'new version','date':'2026-10-08'}
        self.files={'main.py':b'new = 2\n','web.py':b'new = 2\n','logo.png':b'new image','added.txt':b'new file'}
        for p in (patch.object(updater,'ROOT',self.root),patch.object(updater,'DATA',self.data),patch.object(updater,'STATE',self.state),patch.dict(os.environ,JARVIS_DATA_DIR=str(self.data)),patch.object(updater,'_protected_local_changes',return_value={}),patch.object(updater,'_local_source_changes',return_value=[]),patch.object(updater,'_compare_commits',return_value='ahead')):
            p.start();self.addCleanup(p.stop)

    def archive(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for name,value in self.files.items():z.writestr('repo/'+name,value)
        return stream.getvalue()

    def apply(self, check=None):
        with patch.object(updater,'_get',return_value=self.archive()),patch.object(workspace,'validate',side_effect=check or (lambda *args:(True,'checks passed'))):
            return updater.apply(self.info)

    def backup_pull(self, check=None):
        with patch.object(updater,'latest',return_value=self.info), \
             patch.object(updater,'_source_changes_against',return_value=['main.py','deleted.txt','added.txt']), \
             patch.object(updater,'_local_source_changes',side_effect=AssertionError('backed-up pull skips the local-change gate')), \
             patch.object(updater,'_compare_commits',return_value='diverged'), \
             patch.object(updater,'_get',return_value=self.archive()), \
             patch.object(workspace,'validate',side_effect=check or (lambda *args:(True,'checks passed'))):
            return updater.backup_and_pull()

    def test_diverged_pull_backs_up_differing_local_files_then_installs_main(self):
        out=self.backup_pull()
        backup=Path(out['backup'])
        self.assertTrue(backup.is_relative_to(self.data/'yerel_yedek'))
        self.assertEqual((backup/'main.py').read_bytes(),b'old = 1\n')
        self.assertEqual((backup/'deleted.txt').read_bytes(),b'old text')
        self.assertIn('added.txt',(backup/'LISTE.txt').read_text(encoding='utf-8'))
        self.assertEqual(out['added'],['added.txt'])
        self.assertEqual((self.root/'main.py').read_bytes(),b'new = 2\n')
        self.assertFalse((self.root/'deleted.txt').exists())
        state=json.loads(self.state.read_text())
        self.assertEqual((state['sha'],state['sync_state']),('new','synced'))

    def test_diverged_pull_with_failing_checks_keeps_live_files_and_backup(self):
        with self.assertRaisesRegex(RuntimeError,'Aday güncelleme'):
            self.backup_pull(lambda *args:(False,'regression failed'))
        self.assertEqual((self.root/'main.py').read_bytes(),b'old = 1\n')
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')
        self.assertEqual(len(list((self.data/'yerel_yedek').iterdir())),1)

    def test_normal_apply_still_refuses_local_changes(self):
        with patch.object(updater,'_local_source_changes',return_value=['main.py']):
            with self.assertRaisesRegex(RuntimeError,'yerel kaynak değişiklikleri'):
                self.apply()
        self.assertEqual((self.root/'main.py').read_bytes(),b'old = 1\n')

    def test_backup_pull_refuses_older_remote_before_backup_or_download(self):
        with patch.object(updater,'latest',return_value=self.info), \
             patch.object(updater,'_compare_commits',return_value='behind'), \
             patch.object(updater,'_source_changes_against') as compare, \
             patch.object(updater,'_get') as get:
            with self.assertRaisesRegex(RuntimeError,'eski'):
                updater.backup_and_pull()
            compare.assert_not_called();get.assert_not_called()
        self.assertFalse((self.data/'yerel_yedek').exists())
        self.assertEqual((self.root/'main.py').read_bytes(),b'old = 1\n')
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')

    def test_backed_up_apply_cannot_bypass_older_commit_guard(self):
        with patch.object(updater,'_compare_commits',return_value='behind'),patch.object(updater,'_get') as get:
            with self.assertRaisesRegex(RuntimeError,'eski'):
                updater.apply(self.info,backed_up=True)
            get.assert_not_called()
        self.assertEqual((self.root/'main.py').read_bytes(),b'old = 1\n')

    def test_check_does_not_announce_or_apply_older_remote(self):
        with patch.object(updater,'latest',return_value=self.info), \
             patch.object(updater,'_compare_commits',return_value='behind'),patch.object(updater,'apply') as apply:
            for install in (False,True):
                self.assertIn('geride',updater.check(apply_now=install,force=True))
            apply.assert_not_called()
        self.assertEqual(json.loads(self.state.read_text())['pending_sha'],'')

    def test_sync_explains_remote_behind_without_marking_current(self):
        with patch.object(updater,'status',return_value={}),patch.object(updater,'latest',return_value=self.info), \
             patch.object(updater,'_source_changes_against',return_value=['main.py']), \
             patch.object(updater,'_compare_commits',return_value='behind'),patch.object(updater,'mark_current') as mark:
            result=updater.verify_sync()
            self.assertEqual(result['sync_state'],'local_changes')
            self.assertIn('geride',result['sync_msg']);mark.assert_not_called()

    def test_failed_candidate_checks_leave_live_source_metadata_and_environment_untouched(self):
        def failed(candidate,project,python):
            self.assertEqual((project/'main.py').read_bytes(),b'old = 1\n')
            self.assertEqual((candidate/'main.py').read_bytes(),b'new = 2\n')
            return False,'regression failed'
        with self.assertRaisesRegex(RuntimeError,'Aday güncelleme'):
            self.apply(failed)
        self.assertEqual((self.root/'main.py').read_bytes(),b'old = 1\n')
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')
        self.assertIsNone(guard.pending(self.root))

    def test_success_is_pending_start_and_rollback_restores_code_assets_deleted_files_and_sha(self):
        note=self.apply()
        self.assertIn('yeniden başlat',note)
        item=guard.pending(self.root)
        self.assertEqual(item['status'],'awaiting_start')
        self.assertEqual((self.root/'logo.png').read_bytes(),b'new image')
        self.assertFalse((self.root/'deleted.txt').exists())
        self.assertEqual(json.loads(self.state.read_text())['sha'],'new')
        guard.restore(self.root,item)
        self.assertEqual((self.root/'main.py').read_bytes(),b'old = 1\n')
        self.assertEqual((self.root/'logo.png').read_bytes(),b'old image')
        self.assertEqual((self.root/'deleted.txt').read_bytes(),b'old text')
        self.assertFalse((self.root/'added.txt').exists())
        self.assertEqual(json.loads(self.state.read_text()),{'sha':'old','msg':'old'})

    def test_second_live_write_failure_restores_every_source_and_metadata(self):
        atomic=guard.atomic
        count=0
        def write(path,data):
            nonlocal count
            if Path(path).parent==self.root:
                count+=1
                if count==2:raise OSError('disk failure')
            return atomic(path,data)
        with patch.object(guard,'atomic',side_effect=write),self.assertRaisesRegex(OSError,'disk failure'):
            self.apply()
        self.assertEqual((self.root/'main.py').read_bytes(),b'old = 1\n')
        self.assertTrue((self.root/'deleted.txt').exists())
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')
        self.assertIsNone(guard.pending(self.root))

    def test_manual_edit_during_candidate_checks_is_preserved(self):
        def edit(*args):
            (self.root/'main.py').write_bytes(b'manual = 3\n')
            return True,'passed'
        with self.assertRaisesRegex(ValueError,'test sırasında değişmiş'):
            self.apply(edit)
        self.assertEqual((self.root/'main.py').read_bytes(),b'manual = 3\n')
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')
        self.assertIsNone(guard.pending(self.root))

    def test_dependency_candidate_is_selected_then_reverted_without_touching_original_venv(self):
        (self.root/'requirements.lock.txt').write_bytes(b'old==1\n')
        self.files['requirements.lock.txt']=b'new==2\n'
        original=self.root/'.venv';original.mkdir();(original/'keep').write_text('untouched')
        previous=guard.current_python(self.root,'fallback')
        candidate=str(guard.environment_python(guard.store(self.root)/'environments'/'candidate'))
        with patch.object(workspace,'changed_environment',return_value=candidate) as create:
            self.apply()
        create.assert_called_once()
        item=guard.pending(self.root)
        self.assertEqual(guard.current_python(self.root,''),candidate)
        guard.restore(self.root,item)
        self.assertEqual((original/'keep').read_text(),'untouched')
        self.assertEqual(guard.current_python(self.root,''),item['previous_python'])

    def test_official_infrastructure_update_is_tested_and_can_be_rolled_back(self):
        (self.root/'launcher.py').write_bytes(b'pass\n')
        (self.root/'release_guard.py').write_bytes(b'old_guard = True\n')
        self.files['launcher.py']=b'new_launcher = True\n'
        self.files['release_guard.py']=b'new_guard = True\n'
        def check(candidate,project,python):
            self.assertEqual((project/'launcher.py').read_bytes(),b'pass\n')
            self.assertEqual((candidate/'launcher.py').read_bytes(),b'new_launcher = True\n')
            self.assertEqual((candidate/'release_guard.py').read_bytes(),b'new_guard = True\n')
            return True,'passed'
        self.apply(check)
        self.assertEqual((self.root/'launcher.py').read_bytes(),b'new_launcher = True\n')
        item=guard.pending(self.root);self.assertEqual(item['status'],'awaiting_start')
        guard.restore(self.root,item)
        self.assertEqual((self.root/'launcher.py').read_bytes(),b'pass\n')
        self.assertEqual((self.root/'release_guard.py').read_bytes(),b'old_guard = True\n')
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')

    def test_development_candidate_still_cannot_replace_recovery_infrastructure(self):
        (self.root/'launcher.py').write_bytes(b'pass\n')
        with self.assertRaisesRegex(ValueError,'Kurtarma/test'):
            with workspace.candidate(self.root,{'launcher.py':b'new_launcher = True\n'}):
                self.fail('development draft changed recovery infrastructure')
        self.assertEqual((self.root/'launcher.py').read_bytes(),b'pass\n')

    def test_failed_official_infrastructure_candidate_leaves_live_files_unchanged(self):
        (self.root/'launcher.py').write_bytes(b'pass\n')
        self.files['launcher.py']=b'new_launcher = True\n'
        with self.assertRaisesRegex(RuntimeError,'Aday güncelleme'):
            self.apply(lambda *args:(False,'regression failed'))
        self.assertEqual((self.root/'launcher.py').read_bytes(),b'pass\n')
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')
        self.assertIsNone(guard.pending(self.root))

    def test_symlink_target_is_rejected_before_tests_or_source_writes(self):
        outside=Path(self.tmp.name)/'outside';outside.write_bytes(b'private')
        (self.root/'logo.png').unlink()
        try:
            (self.root/'logo.png').symlink_to(outside)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows sembolik bağlantı oluşturma izni vermiyor (WinError 1314).')
            raise
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(outside.read_bytes(),b'private')

    def test_real_failed_start_restores_sources_and_update_sha(self):
        old=b"from pathlib import Path\nPath('restored.txt').write_text('ok')\n"
        (self.root/'gui.py').write_bytes(old)
        self.files['gui.py']=b"raise RuntimeError('candidate startup failed')\n"
        self.apply()
        self.assertEqual(launcher.supervise(self.root,sys.executable,timeout=1,stable=.1),0)
        self.assertEqual((self.root/'gui.py').read_bytes(),old)
        self.assertEqual((self.root/'restored.txt').read_text(),'ok')
        self.assertEqual(json.loads(self.state.read_text())['sha'],'old')
        self.assertIsNone(guard.pending(self.root))
