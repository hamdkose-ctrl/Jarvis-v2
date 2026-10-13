"""Git metadata belongs to the update archive; concurrent source edits still stop install."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import updater
import release_guard


class UpdateMetadataTests(unittest.TestCase):
    def exercise(self, change_during_test=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'; root.mkdir()
            data = Path(folder) / 'data'; data.mkdir()
            for name, contents in {'main.py': b'a=0', 'web.py': b'b=0', '.gitattributes': b'old attributes', '.gitignore': b'old ignore'}.items():
                (root / name).write_bytes(contents)
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                for name, contents in {'main.py': b'a=1', 'web.py': b'b=1', '.gitattributes': b'* text=auto', '.gitignore': b'.venv/'}.items():
                    archive.writestr('repo/' + name, contents)
            def validate(candidate, project, python=None):
                self.assertEqual((candidate / '.gitattributes').read_bytes(), b'* text=auto')
                self.assertEqual((candidate / '.gitignore').read_bytes(), b'.venv/')
                self.assertEqual((root / 'main.py').read_bytes(), b'a=0')
                if change_during_test:
                    (root / '.gitattributes').write_bytes(b'external change')
                return True, 'checks passed'
            with patch.dict(os.environ, {'JARVIS_DATA_DIR': str(data)}), \
                 patch.object(updater, 'ROOT', root), patch.object(updater, 'STATE', data / 'state.json'), \
                 patch.object(updater, '_state', return_value={}), patch.object(release_guard, 'pending', return_value=None), \
                 patch.object(updater, '_get', return_value=raw.getvalue()), \
                 patch('modules.release_workspace.changed_environment', return_value=None), \
                 patch('modules.release_workspace.validate', side_effect=validate):
                info = {'sha': 'candidate', 'msg': 'update', 'date': 'today'}
                if change_during_test:
                    with self.assertRaisesRegex(ValueError, 'test sırasında değişmiş'):
                        updater.apply(info, backed_up=True)
                    self.assertEqual((root / 'main.py').read_bytes(), b'a=0')
                    self.assertEqual((root / '.gitattributes').read_bytes(), b'external change')
                else:
                    updater.apply(info, backed_up=True)
                    self.assertEqual((root / '.gitattributes').read_bytes(), b'* text=auto')
                    self.assertEqual((root / '.gitignore').read_bytes(), b'.venv/')

    def test_archive_preserves_git_metadata(self):
        self.exercise()

    def test_concurrent_metadata_edit_still_blocks_install(self):
        self.exercise(True)
