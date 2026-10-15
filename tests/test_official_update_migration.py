"""Versioned release suites stay paired with their source; drafts keep trusted overlay."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from modules import release_workspace as workspace


class MigrationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.old=Path(self.tmp.name)/'old';self.new=Path(self.tmp.name)/'new'
        for root,value in [(self.old,1),(self.new,2)]:
            (root/'tests').mkdir(parents=True)
            (root/'api.py').write_text('value='+str(value)+'\n')
            (root/'modules').mkdir()
            (root/'modules/__init__.py').touch()
            (root/('required'+str(value))).touch()
            (root/'modules/validation.py').write_text("from pathlib import Path\nimport subprocess,sys\nassert Path('required"+str(value)+"').exists()\ncp=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests'])\nsys.exit(cp.returncode)\n")
            (root/'tests/test_contract.py').write_text('import unittest\nfrom api import value\nclass Contract(unittest.TestCase):\n def test_value(self): self.assertEqual(value,'+str(value)+')\n')
        self.seen=[]

    def check(self,root,python=None,**kwargs):
        self.seen.append((root/'api.py').read_text())
        cp=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests'],cwd=root,capture_output=True,text=True)
        return cp.returncode==0,cp.stdout+cp.stderr


class OfficialMigrationTests(MigrationFixture):
    def test_official_update_runs_both_real_suites_against_their_own_sources(self):
        with patch.object(workspace,'_version_checks',side_effect=self.check),workspace.official_release_validation():
            ok,log=workspace.validate(self.new,self.old)
        self.assertTrue(ok,log);self.assertEqual(self.seen,['value=1\n','value=2\n'])
        self.assertEqual((self.old/'api.py').read_text(),'value=1\n')
        self.assertFalse(workspace._OFFICIAL_RELEASE.get())

    def test_developer_draft_cannot_replace_existing_contract(self):
        with patch('modules.validation.run_checks',side_effect=self.check):
            ok,log=workspace.validate(self.new,self.old)
        self.assertFalse(ok);self.assertIn('FAIL',log)

    def test_failed_candidate_is_still_rejected_in_official_mode(self):
        (self.new/'api.py').write_text('value=99\n')
        with patch.object(workspace,'_version_checks',side_effect=self.check),workspace.official_release_validation():
            ok,log=workspace.validate(self.new,self.old)
        self.assertFalse(ok);self.assertIn('FAIL',log)

    def test_broken_installed_suite_is_reported_separately(self):
        (self.old/'api.py').write_text('value=99\n')
        with patch.object(workspace,'_version_checks',side_effect=self.check),workspace.official_release_validation():
            ok,log=workspace.validate(self.new,self.old)
        self.assertFalse(ok);self.assertIn('Kurulu sürümün kendi kontrolleri başarısız',log)
        self.assertEqual(len(self.seen),1)


class BootstrapMigrationTests(MigrationFixture):
    def test_bootstrap_uses_authenticated_exact_commit_without_preediting_sources(self):
        import io,zipfile
        from scripts import guncelleme_gecisi as migration
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('repo/modules/release_workspace.py',Path(workspace.__file__).read_bytes())
        original=workspace.validate
        def apply(info):
            self.assertEqual(info['sha'],'a'*40)
            ok,log=workspace.validate(self.new,self.old)
            self.assertTrue(ok,log)
            self.assertEqual((self.old/'api.py').read_text(),'value=1\n')
            return 'installed through normal updater'
        with patch.object(migration.updater,'latest',return_value={'sha':'a'*40}),patch.object(migration.updater,'_get',return_value=archive.getvalue()) as get,patch.object(migration.updater,'apply',side_effect=apply),patch('modules.validation.run_checks',side_effect=self.check):
            migration.main()
        self.assertIs(workspace.validate,original)
        self.assertIn('zipball/'+'a'*40,get.call_args.args[0])

    def test_bootstrap_restores_validator_if_normal_apply_rejects_local_changes(self):
        import io,zipfile
        from scripts import guncelleme_gecisi as migration
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:z.writestr('repo/modules/release_workspace.py',Path(workspace.__file__).read_bytes())
        original=workspace.validate
        with patch.object(migration.updater,'latest',return_value={'sha':'a'*40}),patch.object(migration.updater,'_get',return_value=archive.getvalue()),patch.object(migration.updater,'apply',side_effect=RuntimeError('local changes')):
            with self.assertRaises(RuntimeError):migration.main()
        self.assertIs(workspace.validate,original)


class ManifestMigrationTests(MigrationFixture):
    def test_each_release_loads_its_own_required_validation_manifest(self):
        with workspace.official_release_validation():ok,log=workspace.validate(self.new,self.old)
        self.assertTrue(ok,log)
        (self.new/'required2').unlink()
        with workspace.official_release_validation():ok,log=workspace.validate(self.new,self.old)
        self.assertFalse(ok,log)
