import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FolderOrganizeOwnerTests(unittest.TestCase):
    def test_bulk_organize_undo_is_owned_by_the_user_who_confirmed_it(self):
        from modules import files
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'Masaüstü' / 'not.txt'
            target = root / 'Masaüstü' / 'Belgeler' / 'not.txt'
            source.parent.mkdir()
            source.write_text('önemli not', encoding='utf-8')
            with patch.object(files, 'DATA_DIR', root / 'state'):
                self.assertEqual(files.apply_organize([(source, target)], 'alice'), 1)
                self.assertTrue(target.is_file())
                self.assertIsNone(files.undo_organize('bob'))
                self.assertTrue(target.is_file())
                self.assertEqual(files.undo_organize('alice'), 1)
            self.assertTrue(source.is_file())


if __name__ == '__main__':
    unittest.main()
