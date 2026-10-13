import importlib.metadata
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scripts import kurulum_ekleri as setup
from scripts.kurulum_temizligi import remove
from modules import release_workspace


class BundledInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name)

    def fake_download(self,name,output_dir,use_auth_token):
        self.assertEqual(name,'small');self.assertFalse(use_auth_token)
        root=Path(output_dir);root.mkdir(parents=True)
        for f in ('config.json','tokenizer.json','model.bin'):(root/f).write_bytes(b'valid')

    def test_model_prepared_and_validated_locally_then_reused(self):
        download=Mock(side_effect=self.fake_download);load=Mock()
        with patch.dict('sys.modules',{'faster_whisper':SimpleNamespace(download_model=download,WhisperModel=load)}):
            target=setup.prepare_stt(self.data);setup.prepare_stt(self.data)
        download.assert_called_once();self.assertTrue((target/'model.bin').exists())
        self.assertEqual(load.call_count,2)
        self.assertTrue(all(c.kwargs['local_files_only'] for c in load.call_args_list))
        self.assertFalse(list(target.parent.glob('.stt-install-*')))

    def test_failed_download_preserves_existing_incomplete_model(self):
        target=self.data/'models/stt/small';target.mkdir(parents=True)
        (target/'model.bin').write_bytes(b'old')
        with patch.dict('sys.modules',{'faster_whisper':SimpleNamespace(download_model=Mock(side_effect=OSError('offline')),WhisperModel=Mock())}):
            with self.assertRaises(OSError):setup.prepare_stt(self.data)
        self.assertEqual((target/'model.bin').read_bytes(),b'old')

    def test_invalid_staged_model_never_replaces_existing_files(self):
        target=self.data/'models/stt/small';target.mkdir(parents=True)
        (target/'model.bin').write_bytes(b'old')
        with patch.dict('sys.modules',{'faster_whisper':SimpleNamespace(download_model=self.fake_download,WhisperModel=Mock(side_effect=ValueError('corrupt')))}):
            with self.assertRaises(ValueError):setup.prepare_stt(self.data)
        self.assertEqual((target/'model.bin').read_bytes(),b'old')

    def test_promotion_failure_restores_old_model(self):
        target=self.data/'models/stt/small';target.mkdir(parents=True)
        (target/'model.bin').write_bytes(b'old')
        original=Path.rename
        def rename(path,dest):
            if path.parent.name.startswith('.stt-install-'):raise OSError('busy')
            return original(path,dest)
        with patch.dict('sys.modules',{'faster_whisper':SimpleNamespace(download_model=self.fake_download,WhisperModel=Mock())}),patch.object(Path,'rename',rename):
            with self.assertRaises(OSError):setup.prepare_stt(self.data)
        self.assertEqual((target/'model.bin').read_bytes(),b'old')

    def test_plugin_analysis_does_not_execute_plugin_or_copy_secrets(self):
        folder=self.data/'plugins';folder.mkdir()
        marker=self.data/'executed'
        (folder/'example.py').write_text('import requests\nfrom pathlib import Path\nPath('+repr(str(marker))+').touch()\nSECRET="never-copy-this"\ndef handle(a,b):return None\n')
        (folder/'broken.py').write_text('def broken(')
        with patch.object(setup.importlib.metadata,'version',side_effect=importlib.metadata.PackageNotFoundError),patch.object(setup.shutil,'which',return_value=None):
            result=setup.report(self.data)
        self.assertFalse(marker.exists())
        item=next(p for p in result['plugins'] if p['file']=='example.py')
        self.assertTrue(item['has_handle']);self.assertEqual(item['imports'],['pathlib','requests'])
        report=(self.data/'kurulum_raporu.json').read_text()
        self.assertNotIn('never-copy-this',report);self.assertNotIn(str(marker),report)
        self.assertEqual(json.loads(report),result)

    def test_cleanup_keeps_environment_models_personal_files_and_android(self):
        root=self.data; (root/'main.py').touch();(root/'web.py').touch()
        paths=['modules/__pycache__/x.pyc','tests/deep/x.pyc','__pycache__/x.pyc','.ruff_cache/x',
               '.venv/lib/__pycache__/keep.pyc','models/x.bin','notes.json','kurulum.log',
               '.claude/skills/keep.pyc','android/Jarvis3/keep.pyc','modules/current.py']
        for name in paths:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('keep')
        removed=remove(root)
        self.assertIn('modules/__pycache__',removed)
        for name in paths[:4]:self.assertFalse((root/name).exists())
        for name in paths[4:]:self.assertTrue((root/name).exists(),name)
        self.assertEqual(remove(root),[])

    def test_cleanup_never_follows_link_outside_source_tree(self):
        root=self.data/'project';root.mkdir();(root/'main.py').touch();(root/'web.py').touch()
        outside=self.data/'outside';outside.mkdir();(outside/'keep.pyc').touch()
        (root/'modules').mkdir()
        try:(root/'modules/__pycache__').symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('symlink unavailable')
        remove(root);self.assertTrue((outside/'keep.pyc').exists())

    def test_bundle_dependency_changes_build_candidate_environment(self):
        (self.data/'requirements.lock.txt').write_text('requests==1')
        (self.data/'requirements-bundle.txt').write_text('faster-whisper')
        cp=SimpleNamespace(returncode=0)
        with patch.object(release_workspace.guard,'store',return_value=self.data/'releases'),patch.object(release_workspace.subprocess,'run',return_value=cp) as run:
            self.assertIsNotNone(release_workspace.changed_environment(self.data,{'requirements-bundle.txt'},self.data))
        command=run.call_args_list[1].args[0]
        self.assertIn(str(self.data/'requirements-bundle.txt'),command)
        self.assertIn(str(self.data/'requirements.lock.txt'),command)

if __name__=='__main__':unittest.main()
