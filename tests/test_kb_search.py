"""Searching uploaded files: FTS5 keyword index with page/slide/sheet locations, only for files the user added."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import docs, kb


class Profile:
    def __init__(self, slug='hamdi'):
        self.slug, self.data, self._id, self.saves = slug, {}, 0, 0

    def _new_id(self):
        self._id += 1
        return self._id

    def save(self):
        self.saves += 1


class KbSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        p = patch.object(kb, 'ROOT', self.dir / 'kb'); p.start(); self.addCleanup(p.stop)
        self.profile = Profile()

    def file(self, name, text='x'):
        path = self.dir / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    def add(self, name, text):
        with patch.object(docs, 'read_document', return_value=text):
            return kb.add(self.profile, self.file(name, text))

    def test_finds_inflected_words_with_file_and_page(self):
        self.add('Sözleşme.pdf', 'Taraflar\fKİRA BEDELİ aylık 15.000 TL olup her ayın 5inde ödenir.\fFesih şartları')
        self.add('Teklif.xlsx', '## Özet\nKalem | Tutar\nVida | 1200\n## Detay\nSomun | 300')
        hits = kb.search(self.profile, 'kira bedeli hangi dosyadaydı?')
        self.assertEqual(hits[0][0], 'Sözleşme.pdf › sayfa 2')
        self.assertIn('15.000 TL', hits[0][1])
        self.assertEqual(kb.search(self.profile, 'vidaların tutarı')[0][0], 'Teklif.xlsx › sayfa "Özet"')
        self.assertEqual(kb.search(self.profile, 'hangi dosyada geçiyor'), [])   # only question words

    def test_slides_and_legacy_documents_are_indexed(self):
        self.add('Sunum.pptx', '<!-- Slide number: 1 -->\n# Giriş\n<!-- Slide number: 7 -->\n# Bütçe planı')
        self.assertEqual(kb.search(self.profile, 'bütçe')[0][0], 'Sunum.pptx › slayt 7')
        # A document added before the index existed is indexed on the next search.
        kb._dir(self.profile).joinpath('99.txt').write_text('Eski not: sigorta poliçesi', encoding='utf-8')
        self.profile.data['kb'].append({'id': 99, 'title': 'eski.txt', 'path': 'x'})
        self.assertEqual(kb.search(self.profile, 'poliçe')[0][0], 'eski.txt')

    def test_same_file_is_not_added_twice_and_changed_file_replaces_old(self):
        path = self.file('not.txt', 'ilk sürüm elma')
        first = kb.add(self.profile, path)
        self.assertIs(kb.add(self.profile, path), first)
        Path(path).write_text('ikinci sürüm armut ve daha uzun', encoding='utf-8')
        second = kb.add(self.profile, path)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(len(kb.list_docs(self.profile)), 1)
        self.assertEqual(kb.search(self.profile, 'elma'), [])
        self.assertEqual(kb.search(self.profile, 'armut')[0][0], 'not.txt')
        kb.remove(self.profile, second['id'])
        self.assertEqual(kb.search(self.profile, 'armut'), [])

    def test_users_have_separate_indexes(self):
        self.add('hamdi.txt', 'maaş bordrosu')
        other = Profile('ebru')
        self.assertEqual(kb.search(other, 'bordro'), [])

    def test_remember_skips_images_and_unreadable_files(self):
        self.assertIsNone(kb.remember(self.profile, self.file('foto.png')))
        with patch.object(docs, 'read_document', side_effect=ValueError('şifreli')):
            self.assertIsNone(kb.remember(self.profile, self.file('gizli.docx')))
        self.assertEqual(kb.list_docs(self.profile), [])

    def test_answer_cites_location_and_natural_questions_route_here(self):
        self.add('Sözleşme.pdf', 'Giriş\fKira bedeli aylık 15.000 TL.')
        with patch.object(kb, 'ask', return_value='Aylık 15.000 TL.') as ask:
            reply = kb.handle('kira bedeli hangi dosyadaydı', self.profile)
        self.assertIn('Kaynak: Sözleşme.pdf › sayfa 2', reply)
        self.assertIn('[Sözleşme.pdf › sayfa 2]', ask.call_args.args[0])
        self.assertIsNone(kb.handle('bugün hava nasıl', self.profile))
        self.assertIsNone(kb.handle('yüklediğim dosyayı özetle', self.profile))   # file commands stay elsewhere
        self.assertIsNone(kb.handle('hangi dosyayı açayım', self.profile))
        with patch.object(kb, 'ask', return_value='Evet.'):
            self.assertIn('Kaynak', kb.handle('yüklediğim dosyalarda kira geçiyor mu', self.profile))
        self.assertIsNone(kb.handle('hangi dosya', Profile('bos')))   # no files: leave it to other commands

    def test_keyword_search_never_calls_embeddings(self):
        self.add('a.txt', 'fatura listesi')
        with patch.object(kb.llm, 'embed', side_effect=AssertionError('quota')):
            self.assertEqual(kb.search(self.profile, 'faturaların')[0][0], 'a.txt')

    def test_document_cache_reads_once_and_keeps_pdf_pages(self):
        path = self.file('k.pdf')
        with patch.object(docs, 'read_pdf_isolated', return_value='a\fb') as pdf:
            self.assertEqual(docs.read_document(path, keep_pages=True, cache=True), 'a\fb')
            self.assertEqual(docs.read_document(path, cache=True), 'a\nb')
            self.assertEqual(pdf.call_count, 1)
            self.assertEqual(docs.read_document(path), 'a\nb')
            self.assertEqual(pdf.call_count, 2)


if __name__ == '__main__':
    unittest.main()
