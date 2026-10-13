"""Dosyalar arama kutusu: belge içinde arama (Bilgi tabanı ekranı yok), yüklenen belgeler aranabilir olur."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import docs, kb, nxapi


class Profile:
    def __init__(self):
        self.slug, self.data, self._id = 'hamdi', {}, 0

    def _new_id(self):
        self._id += 1
        return self._id

    def save(self):
        pass


class FilesContentSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        p = patch.object(kb, 'ROOT', self.dir / 'kb'); p.start(); self.addCleanup(p.stop)
        self.profile = Profile()

    def file(self, name, text='x'):
        path = self.dir / name
        path.write_text(text, encoding='utf-8')
        return path

    def test_index_files_makes_uploads_searchable_and_skips_unsupported(self):
        doc = self.file('Sözleşme.pdf'); other = self.file('resim.png'); broken = self.file('bos.pdf')

        def read(path, **kwargs):
            return 'Taraflar\fKİRA BEDELİ aylık 15.000 TL ödenir.' if Path(path).name == 'Sözleşme.pdf' else ''
        with patch.object(docs, 'read_document', side_effect=read):
            done = kb.index_files(self.profile, [doc, other, broken])
        self.assertEqual(done, 1)   # png desteklenmez, boş pdf okunamaz ve atlanır
        hits = kb.file_hits(self.profile, 'kira bedeli ne kadar?')
        self.assertEqual([h['name'] for h in hits], ['Sözleşme.pdf'])
        self.assertEqual(hits[0]['path'], str(doc))
        self.assertIn('15.000 TL', hits[0]['snippet'])
        self.assertEqual(hits[0]['where'], 'sayfa 2')

    def test_each_file_appears_once_and_no_match_is_empty(self):
        doc = self.file('Rapor.docx')
        with patch.object(docs, 'read_document', return_value='vida vida vida\fvida somun\fvida cıvata'):
            kb.index_files(self.profile, [doc])
        self.assertEqual(len(kb.file_hits(self.profile, 'vida')), 1)
        self.assertEqual(kb.file_hits(self.profile, 'zzzyyyxxx'), [])

    def test_describe_file_matches_list_row_shape(self):
        path = self.file('not.txt', 'merhaba')
        row = nxapi.describe_file(path)
        for key in ('path', 'name', 'ext', 'cat', 'size', 'mtime', 'folder', 'mine', 'where'):
            self.assertIn(key, row)
        self.assertEqual((row['name'], row['ext']), ('not.txt', 'txt'))
        self.assertIsNone(nxapi.describe_file(self.dir / 'yok.pdf'))


if __name__ == '__main__':
    unittest.main()
