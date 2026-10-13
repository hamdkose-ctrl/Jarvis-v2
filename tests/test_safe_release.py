"""Real file transactions and supervisor children; no model or external package service."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import release_guard as guard
import launcher
from modules import developer as dev, release_workspace as workspace


class SafeReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'; self.root.mkdir()
        self.data = Path(self.tmp.name) / 'data'
        p = patch.dict(os.environ, JARVIS_DATA_DIR=str(self.data)); p.start(); self.addCleanup(p.stop)
        self.source = self.root / 'example.py'; self.source.write_bytes(b'value = 1\n')
        self.record = {'example.py': {'before': base64.b64encode(self.source.read_bytes()).decode(),
                                     'after': guard.digest(b'value = 2\n')}}

    def install(self, records=None, python=None):
        item = guard.prepare(self.root, records or self.record, 'alice', python)
        self.source.write_bytes(b'value = 2\n')
        guard.installed(self.root, item)
        return item

    def test_child_resisting_termination_is_killed_and_reaped(self):
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('candidate', 10), 0]
        launcher._stop_child(child)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_args_list[0].kwargs, {'timeout': 10})
        self.assertEqual(child.wait.call_count, 2)

    def test_already_exited_child_is_not_terminated(self):
        child = Mock()
        child.poll.return_value = 0
        launcher._stop_child(child)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_child_exiting_during_termination_is_still_reaped(self):
        child = Mock()
        child.poll.return_value = None
        child.terminate.side_effect = ProcessLookupError()
        launcher._stop_child(child)
        child.wait.assert_called_once_with(timeout=10)
        child.kill.assert_not_called()

    def test_interrupted_supervision_stops_child_and_keeps_recovery_journal(self):
        item = self.install()
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('candidate', 10), 0]
        with patch.object(launcher.subprocess, 'Popen', return_value=child), patch.object(launcher, '_markers_ready', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                launcher.supervise(self.root, sys.executable)
        child.kill.assert_called_once()
        self.assertEqual(guard.pending(self.root)['id'], item['id'])
        self.assertEqual(self.source.read_bytes(), b'value = 2\n')

    def test_candidate_contains_assets_but_not_venv_or_private_data_and_is_deleted(self):
        (self.root / 'webui').mkdir(); (self.root / 'webui/logo.png').write_bytes(b'original-image')
        (self.root / '.venv').mkdir(); (self.root / '.venv/large').write_bytes(b'packages')
        (self.root / '.env').write_text('secret')
        with workspace.candidate(self.root, {'example.py': b'value = 2\n', 'webui/logo.png': b'new-image'}) as candidate:
            self.assertEqual(self.source.read_bytes(), b'value = 1\n')
            self.assertEqual((candidate / 'webui/logo.png').read_bytes(), b'new-image')
            self.assertFalse((candidate / '.venv').exists()); self.assertFalse((candidate / '.env').exists())
            location = candidate
        self.assertFalse(location.exists())

    def test_recovery_infrastructure_cannot_be_edited_using_path_aliases(self):
        for name in ('./launcher.py', 'Launcher.py', './modules/validation.py', 'MODULES/release_workspace.py'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError), workspace.candidate(self.root, {name: b'changed'}):
                    pass
                with patch.object(dev, 'PROJECT', self.root), self.assertRaises(ValueError):
                    dev._path(name)

    def test_binary_asset_rollback_restores_original_bytes_and_removes_added_file(self):
        asset = self.root / 'logo.png'; asset.write_bytes(b'old\x00image')
        records = {'logo.png': {'before': base64.b64encode(asset.read_bytes()).decode(), 'after': guard.digest(b'new\x00image')},
                   'added.png': {'before': None, 'after': guard.digest(b'added')}}
        item = guard.prepare(self.root, records, 'alice')
        asset.write_bytes(b'new\x00image'); (self.root / 'added.png').write_bytes(b'added')
        guard.restore(self.root, item)
        self.assertEqual(asset.read_bytes(), b'old\x00image'); self.assertFalse((self.root / 'added.png').exists())

    def test_interrupted_apply_recovers_before_application_imports(self):
        item = guard.prepare(self.root, self.record, 'alice')
        self.source.write_bytes(b'value = 2\n')
        self.assertTrue(guard.recover(self.root)); self.assertEqual(self.source.read_bytes(), b'value = 1\n')
        self.assertIsNone(guard.pending(self.root))

    def test_interrupted_undo_of_confirmed_release_recreates_pending_pointer(self):
        second=self.root/'second.txt';second.write_bytes(b'old')
        records=dict(self.record)
        records['second.txt']={'before':base64.b64encode(b'old').decode(),'after':guard.digest(b'new')}
        item=guard.prepare(self.root,records,'alice')
        self.source.write_bytes(b'value = 2\n');second.write_bytes(b'new')
        guard.installed(self.root,item);guard.confirm(self.root,item)
        self.assertIsNone(guard.pending(self.root))
        atomic=guard.atomic
        def interrupted(path,data):
            if Path(path)==second:raise OSError('interrupted undo')
            if Path(path)==self.source:self.assertEqual(guard.pending(self.root)['status'],'rolling_back')
            return atomic(path,data)
        with patch.object(guard,'atomic',side_effect=interrupted),self.assertRaises(OSError):
            guard.restore(self.root,item)
        self.assertEqual(self.source.read_bytes(),b'value = 1\n')
        self.assertEqual(guard.pending(self.root)['status'],'rolling_back')
        self.assertTrue(guard.recover(self.root))
        self.assertEqual(second.read_bytes(),b'old')
        self.assertIsNone(guard.pending(self.root))

    def test_undo_cannot_replace_another_pending_release(self):
        first=self.install();guard.confirm(self.root,first)
        second=self.install()
        with self.assertRaisesRegex(ValueError,'Başka bir sürüm'):
            guard.restore(self.root,first)
        self.assertEqual(guard.pending(self.root)['id'],second['id'])
        self.assertEqual(self.source.read_bytes(),b'value = 2\n')

    def test_recovery_checks_all_files_before_writing(self):
        records = dict(self.record); records['other.py'] = {'before': None, 'after': guard.digest(b'new')}
        item = guard.prepare(self.root, records, 'alice'); self.source.write_bytes(b'value = 2\n')
        (self.root / 'other.py').write_bytes(b'manual-edit')
        with self.assertRaises(ValueError): guard.restore(self.root, item)
        self.assertEqual(self.source.read_bytes(), b'value = 2\n'); self.assertIsNotNone(guard.pending(self.root))

    def test_dependency_pointer_is_reverted_with_code(self):
        previous = guard.current_python(self.root, sys.executable)
        item = self.install(python=str(self.data / 'new-python'))
        self.assertEqual(guard.current_python(self.root, ''), str(self.data / 'new-python'))
        guard.restore(self.root, item)
        self.assertEqual(guard.current_python(self.root, ''), previous)

    def test_pending_release_blocks_another_user(self):
        self.install()
        with self.assertRaises(ValueError): guard.prepare(self.root, self.record, 'bob')

    def test_cleanup_keeps_three_releases_and_pending_and_original_environment(self):
        original = self.root / '.venv'; original.mkdir(); (original / 'keep').write_text('original')
        for _ in range(5):
            item = self.install(); guard.confirm(self.root, item)
        self.assertEqual(len(list((guard.store(self.root) / 'history').glob('*.json'))), 3)
        item = self.install(); guard.cleanup(self.root)
        self.assertIsNotNone(guard.pending(self.root)); self.assertTrue((original / 'keep').exists())
        self.assertTrue((guard.store(self.root) / 'history' / (item['id'] + '.json')).exists())

    def test_backup_limit_rejects_before_mutation(self):
        with patch.object(guard, 'MAX_BYTES', 10):
            with self.assertRaises(ValueError): guard.prepare(self.root, self.record, 'alice')
        self.assertEqual(self.source.read_bytes(), b'value = 1\n'); self.assertIsNone(guard.pending(self.root))

    def test_supervisor_rolls_back_real_syntax_failure_and_relaunches_previous(self):
        gui = self.root / 'gui.py'; old = "from pathlib import Path\nPath('restored.txt').write_text('ok')\n"
        gui.write_text(old)
        broken = b'def broken(\n'
        records = {'gui.py': {'before': base64.b64encode(gui.read_bytes()).decode(), 'after': guard.digest(broken)}}
        item = guard.prepare(self.root, records, 'alice'); gui.write_bytes(broken); guard.installed(self.root, item)
        self.assertEqual(launcher.supervise(self.root, sys.executable, timeout=2, stable=0.1), 0)
        self.assertEqual(gui.read_text(), old); self.assertTrue((self.root / 'restored.txt').exists())
        self.assertIsNone(guard.pending(self.root))

    def test_supervisor_recovers_when_candidate_python_cannot_start(self):
        gui = self.root / 'gui.py'
        old = b"from pathlib import Path\nPath('restored.txt').write_text('ok')\n"
        new = b"raise RuntimeError('candidate')\n"
        gui.write_bytes(old)
        item = guard.prepare(self.root, {'gui.py': {'before': base64.b64encode(old).decode(), 'after': guard.digest(new)}}, 'alice', python=str(self.root / 'missing-python'))
        gui.write_bytes(new)
        guard.installed(self.root, item)
        self.assertEqual(launcher.supervise(self.root, sys.executable, timeout=1), 0)
        self.assertEqual(gui.read_bytes(), old)
        self.assertTrue((self.root / 'restored.txt').exists())
        self.assertIsNone(guard.pending(self.root))
        self.assertEqual(guard.current_python(self.root, ''), sys.executable)

    def test_marker_disappearing_during_health_check_is_not_a_startup_exception(self):
        with patch.object(Path, 'read_text', side_effect=['boot-id', FileNotFoundError()]):
            self.assertFalse(launcher._markers_ready(self.root, 'boot-id'))

    def test_supervisor_requires_both_markers_and_confirms_real_child(self):
        gui = self.root / 'gui.py'; old = b'pass\n'
        gui.write_bytes(old)
        code = b"import os,time\nfrom pathlib import Path\np=Path(os.environ['JARVIS_BOOT_MARKERS'])\nfor n in ('engine','web'):(p/n).write_text(os.environ['JARVIS_BOOT_ID'])\ntime.sleep(.4)\n"
        item = guard.prepare(self.root, {'gui.py': {'before': base64.b64encode(old).decode(), 'after': guard.digest(code)}}, 'alice')
        gui.write_bytes(code); guard.installed(self.root, item)
        self.assertEqual(launcher.supervise(self.root, sys.executable, timeout=2, stable=.1), 0)
        self.assertEqual(gui.read_bytes(), code); self.assertIsNone(guard.pending(self.root))
        self.assertEqual(guard.read(guard.store(self.root)/'history'/(item['id']+'.json'))['status'], 'confirmed')

    def test_supervisor_does_not_accept_one_marker(self):
        gui = self.root / 'gui.py'; old=b'pass\n'; gui.write_bytes(old)
        code=b"import os,time\nfrom pathlib import Path\n(Path(os.environ['JARVIS_BOOT_MARKERS'])/'web').write_text(os.environ['JARVIS_BOOT_ID'])\ntime.sleep(5)\n"
        item=guard.prepare(self.root, {'gui.py':{'before':base64.b64encode(old).decode(),'after':guard.digest(code)}},'alice')
        gui.write_bytes(code);guard.installed(self.root,item)
        self.assertEqual(launcher.supervise(self.root,sys.executable,timeout=.3,stable=.1),0)
        self.assertEqual(gui.read_bytes(),old)

    def test_failed_dependency_install_preserves_environment_and_removes_candidate(self):
        (self.root / 'requirements.lock.txt').write_text('example==1\n')
        original=self.root/'.venv';original.mkdir();(original/'keep').write_text('working')
        with patch.object(workspace.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],1)]):
            with self.assertRaises(RuntimeError):workspace.changed_environment(self.root,{'requirements.lock.txt'},self.root)
        self.assertEqual((original/'keep').read_text(),'working')
        self.assertFalse(list((guard.store(self.root)/'environments').glob('*')))

    def test_test_edits_are_checked_against_original_suite_first(self):
        (self.root/'tests').mkdir();(self.root/'tests/test_original.py').write_text('old test')
        with workspace.candidate(self.root,{'tests/test_original.py':b'weakened test'}) as candidate:
            def check(root):
                self.assertEqual((root/'tests/test_original.py').read_text(),'old test')
                return False,'regression'
            with patch('modules.validation.run_checks',side_effect=check):
                self.assertFalse(workspace.validate(candidate,self.root)[0])


class CandidateDeveloperTests(unittest.TestCase):
    def test_failed_candidate_tests_never_touch_installed_sources_even_temporarily(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,JARVIS_DATA_DIR=folder+'/data'):
            root=Path(folder)/'project';root.mkdir();source=root/'example.py';source.write_text('value = 1\n')
            with patch.object(dev,'PROJECT',root),patch.object(dev,'STORE',Path(folder)/'state'),patch.object(dev,'_AUTH',set()):
                dev.unlock('alice','test-pass');dev.enable('alice');state=dev._load('alice')
                dev._stage(state,'example.py','value = 2\n');dev._save('alice',state)
                def check(candidate,python):
                    self.assertEqual(source.read_text(),'value = 1\n')
                    self.assertEqual((candidate/'example.py').read_text(),'value = 2\n')
                    return False,'failed'
                with patch.object(dev,'_test',side_effect=check),patch.object(dev,'_atomic',wraps=dev._atomic) as write:
                    response=dev.handle('alice','değişiklikleri uygula')
                self.assertIn('değiştirilmedi',response)
                self.assertFalse(any(call.args[0]==source for call in write.call_args_list))
                self.assertIsNone(guard.pending(root))

    def test_manual_edit_during_test_prevents_install_and_preserves_edit(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,JARVIS_DATA_DIR=folder+'/data'):
            root=Path(folder)/'project';root.mkdir();source=root/'example.py';source.write_text('value = 1\n')
            with patch.object(dev,'PROJECT',root),patch.object(dev,'STORE',Path(folder)/'state'),patch.object(dev,'_AUTH',set()):
                dev.unlock('alice','test-pass');dev.enable('alice');state=dev._load('alice')
                dev._stage(state,'example.py','value = 2\n');dev._save('alice',state)
                def check(*args):source.write_text('value = 99\n');return True,'OK'
                with patch.object(dev,'_test',side_effect=check):response=dev.handle('alice','değişiklikleri uygula')
                self.assertIn('test sırasında değişmiş',response);self.assertEqual(source.read_text(),'value = 99\n')
                self.assertIsNone(guard.pending(root))

    def test_png_reference_is_staged_and_undone_as_bytes(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,JARVIS_DATA_DIR=folder+'/data'):
            root=Path(folder)/'project';root.mkdir();asset=root/'logo.png';asset.write_bytes(b'old-image')
            with patch.object(dev,'PROJECT',root),patch.object(dev,'STORE',Path(folder)/'state'),patch.object(dev,'_AUTH',set()):
                dev.unlock('alice','test-pass');dev.enable('alice');state=dev._load('alice')
                ref=dev._folder('alice')/'references'/'example.png';ref.parent.mkdir();ref.write_bytes(b'new-image')
                state['references'].append({'id':'example','kind':'image','name':'example.png'})
                dev._stage_asset('alice',state,'logo.png','example');dev._save('alice',state)
                self.assertEqual(asset.read_bytes(),b'old-image')
                with patch.object(dev,'_test',return_value=(True,'OK')):dev.handle('alice','değişiklikleri uygula')
                self.assertEqual(asset.read_bytes(),b'new-image')
                dev.handle('alice','son geliştirmeyi geri al');self.assertEqual(asset.read_bytes(),b'old-image')

    def test_interrupted_user_undo_is_journaled_before_source_changes_and_recovers(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, JARVIS_DATA_DIR=folder + '/data'):
            root = Path(folder) / 'project';root.mkdir()
            first, second = root / 'first.py', root / 'second.txt'
            first.write_bytes(b'value = 1\n');second.write_bytes(b'old')
            with patch.object(dev, 'PROJECT', root), patch.object(dev, 'STORE', Path(folder) / 'state'), patch.object(dev, '_AUTH', set()):
                dev.unlock('alice', 'test-pass');dev.enable('alice')
                state = dev._load('alice')
                dev._stage(state, 'first.py', 'value = 2\n');dev._stage(state, 'second.txt', 'new');dev._save('alice', state)
                with patch.object(dev, '_test', return_value=(True, 'OK')):
                    dev.handle('alice', 'değişiklikleri uygula')
                original_atomic = guard.atomic
                def interrupted(path, data):
                    if Path(path) == first:
                        self.assertEqual(guard.pending(root)['status'], 'rolling_back')
                    if Path(path) == second:
                        raise OSError('interrupted second write')
                    return original_atomic(path, data)
                with patch.object(guard, 'atomic', side_effect=interrupted), self.assertRaises(OSError):
                    dev.handle('alice', 'son geliştirmeyi geri al')
                self.assertEqual(first.read_bytes(), b'value = 1\n')
                self.assertEqual(second.read_bytes(), b'new')
                self.assertEqual(guard.pending(root)['status'], 'rolling_back')
                self.assertTrue(guard.recover(root))
                self.assertEqual(second.read_bytes(), b'old')
                self.assertIsNone(guard.pending(root))
                self.assertEqual(set(dev._load('alice')['draft']), {'first.py', 'second.txt'})

    def test_undo_rejects_journal_owned_by_another_user_before_writing(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, JARVIS_DATA_DIR=folder + '/data'):
            root = Path(folder) / 'project';root.mkdir();source = root / 'example.py';source.write_bytes(b'value = 1\n')
            with patch.object(dev, 'PROJECT', root), patch.object(dev, 'STORE', Path(folder) / 'state'), patch.object(dev, '_AUTH', set()):
                dev.unlock('alice', 'test-pass');dev.enable('alice');state = dev._load('alice')
                dev._stage(state, 'example.py', 'value = 2\n');dev._save('alice', state)
                with patch.object(dev, '_test', return_value=(True, 'OK')):
                    dev.handle('alice', 'değişiklikleri uygula')
                item = guard.pending(root);item['owner'] = 'bob';guard.update(root, item, item['status'])
                with self.assertRaisesRegex(ValueError, 'bu kullanıcıya ait değil'):
                    dev.handle('alice', 'son geliştirmeyi geri al')
                self.assertEqual(source.read_bytes(), b'value = 2\n')


class InstallationPreflightTests(unittest.TestCase):
    def test_pending_release_skips_package_repair(self):
        import launcher
        with patch.object(launcher.guard, 'recover') as recover, patch.object(launcher.guard, 'pending', return_value={'status': 'awaiting_start'}), patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(launcher.check_installation(), 0)
            recover.assert_called_once()
            run.assert_not_called()

    def test_healthy_installation_checks_selected_python_and_cleans_old_install(self):
        import launcher
        with patch.object(launcher.guard, 'recover'), patch.object(launcher.guard, 'pending', return_value=None), patch.object(launcher.guard, 'current_python', return_value='selected-python'), patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, patch.object(launcher.subprocess, 'call', return_value=0) as cleanup:
            self.assertEqual(launcher.check_installation(), 0)
            self.assertEqual(run.call_args.args[0][0], 'selected-python')
            self.assertEqual(cleanup.call_args.args[0][0], 'selected-python')

    def test_missing_packages_request_repair_without_starting_gui(self):
        import launcher
        with patch.object(launcher.guard, 'recover'), patch.object(launcher.guard, 'pending', return_value=None), patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=1)), patch.object(launcher.subprocess, 'call') as start:
            self.assertEqual(launcher.check_installation(), 2)
            start.assert_not_called()
