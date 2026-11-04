"""Tek dosya işlemleri gerçek (geçici) klasörlerde denenir; kullanıcının dosyalarına dokunulmaz."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_ops, files, llm, permission_audit, permission_policy, requests_state


class FileOpsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        token = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, token)
        token = requests_state._current.set(None); self.addCleanup(requests_state._current.reset, token)
        self.enterContext(patch.object(permission_policy, 'ROOT', self.home / 'policy'))
        self.enterContext(patch.object(permission_audit, 'DATA_DIR', self.home))
        for name in ('Downloads', 'Desktop', 'Documents', 'Pictures'):
            (self.home / name).mkdir()
        self.enterContext(patch.object(files.Path, 'home', return_value=self.home))
        self.enterContext(patch.object(file_ops.Path, 'home', return_value=self.home))
        self.enterContext(patch.object(file_ops, 'DATA_DIR', self.home))
        self.downloads, self.desktop, self.documents = self.home / 'Downloads', self.home / 'Desktop', self.home / 'Documents'

    def write(self, folder, name, text='x'):
        path = folder / name
        path.write_text(text, encoding='utf-8')
        return path

    def test_move_by_name_without_extension_and_turkish_suffixes(self):
        for command in ('rapor dosyasını belgelere taşı', 'rapor.pdf dosyasını belgelere taşı', "rapor'u belgelere taşı",
                        'indirilenlerdeki rapor dosyasını belgeler klasörüne taşı', 'lütfen Rapor dosyasını Belgelere taşır mısın'):
            with self.subTest(command=command):
                source = self.write(self.downloads, 'rapor.pdf')
                reply = file_ops.handle(command)
                self.assertIn('taşıdım', reply)
                self.assertFalse(source.exists())
                self.assertTrue((self.documents / 'rapor.pdf').exists())
                (self.documents / 'rapor.pdf').unlink()

    def test_move_never_overwrites_and_undo_restores(self):
        self.write(self.documents, 'rapor.pdf', 'eski')
        self.write(self.downloads, 'rapor.pdf', 'yeni')
        self.assertIn('taşıdım', file_ops.handle('indirilenlerdeki rapor dosyasını belgelere taşı'))
        self.assertEqual((self.documents / 'rapor.pdf').read_text(encoding='utf-8'), 'eski')
        self.assertEqual((self.documents / 'rapor (1).pdf').read_text(encoding='utf-8'), 'yeni')
        self.assertIn('geri aldım', file_ops.handle('son dosya işlemini geri al'))
        self.assertTrue((self.downloads / 'rapor.pdf').exists())
        self.assertFalse((self.documents / 'rapor (1).pdf').exists())
        self.assertIn('yok', file_ops.handle('son dosya işlemini geri al'))

    def test_missing_ambiguous_and_same_folder_are_reported_not_guessed(self):
        self.assertIn('bulamadım', file_ops.handle('yok dosyasını belgelere taşı'))
        self.write(self.downloads, 'plan.txt'); self.write(self.desktop, 'plan.txt')
        self.assertIn('Birden fazla', file_ops.handle('plan dosyasını belgelere taşı'))
        self.assertTrue((self.downloads / 'plan.txt').exists() and (self.desktop / 'plan.txt').exists())
        self.assertIn('zaten', file_ops.handle('masaüstündeki plan dosyasını masaüstüne taşı'))

    def test_rename_keeps_extension_refuses_overwrite_and_bad_names(self):
        source = self.write(self.desktop, 'eski.docx')
        self.assertIn('yaptım', file_ops.handle('eski dosyasının adını Yeni Rapor yap'))
        self.assertTrue((self.desktop / 'Yeni Rapor.docx').exists() and not source.exists())
        self.write(self.desktop, 'baska.docx')
        self.assertIn('zaten var', file_ops.handle('baska dosyasının adını Yeni Rapor yap'))
        self.assertTrue((self.desktop / 'baska.docx').exists())
        for bad in ('a/b', 'a:b', 'con', 'x?'):
            with self.subTest(bad=bad):
                reply = file_ops.handle('baska dosyasının adını %s yap' % bad)
                self.assertTrue(reply.startswith(('Yeni ad geçersiz', 'Bu ad Windows')) or 'bulamadım' in reply, reply)
        self.assertTrue((self.desktop / 'baska.docx').exists())

    def test_rename_undo(self):
        self.write(self.desktop, 'eski.txt')
        file_ops.handle('eski dosyasının adını yeni yap')
        self.assertTrue((self.desktop / 'yeni.txt').exists())
        self.assertIn('geri aldım', file_ops.handle('son dosya işlemini geri al'))
        self.assertTrue((self.desktop / 'eski.txt').exists())

    def test_create_text_file_with_content_never_overwrites_and_can_be_undone(self):
        reply = file_ops.handle('masaüstüne alışveriş adında bir metin dosyası oluştur ve içine süt ekmek yaz')
        self.assertIn('oluşturdum', reply)
        self.assertEqual((self.desktop / 'alışveriş.txt').read_text(encoding='utf-8'), 'süt ekmek\n')
        file_ops.handle('masaüstüne alışveriş adında bir metin dosyası oluştur')
        self.assertEqual((self.desktop / 'alışveriş.txt').read_text(encoding='utf-8'), 'süt ekmek\n')
        self.assertTrue((self.desktop / 'alışveriş (1).txt').exists())
        self.assertIn('geri aldım', file_ops.handle('son dosya işlemini geri al'))
        self.assertFalse((self.desktop / 'alışveriş (1).txt').exists())
        self.assertTrue((self.desktop / 'alışveriş.txt').exists())

    def test_undo_never_deletes_a_text_file_the_user_edited_afterwards(self):
        file_ops.handle('masaüstüne not adında bir metin dosyası oluştur ve içine merhaba yaz')
        created = self.desktop / 'not.txt'
        created.write_text('kullanıcı düzenledi', encoding='utf-8')
        self.assertIn('dokunmadım', file_ops.handle('son dosya işlemini geri al'))
        self.assertEqual(created.read_text(encoding='utf-8'), 'kullanıcı düzenledi')

    def test_undo_record_is_per_user(self):
        self.write(self.downloads, 'rapor.pdf')
        file_ops.handle('rapor dosyasını belgelere taşı', 'alice')
        token = llm._key_context.set('bob')
        try:
            self.assertIn('yok', file_ops.handle('son dosya işlemini geri al', 'bob'))
        finally:
            llm._key_context.reset(token)
        self.assertTrue((self.documents / 'rapor.pdf').exists())
        self.assertIn('geri aldım', file_ops.handle('son dosya işlemini geri al', 'alice'))
        self.assertTrue((self.downloads / 'rapor.pdf').exists())

    def test_only_known_folders_and_unrelated_sentences_are_ignored(self):
        self.write(self.downloads, 'rapor.pdf')
        for command in ('rapor dosyasını sisteme taşı', 'bu işi yarına taşı', 'rapor dosyasını sil', 'toplantıyı belgelere taşı'):
            with self.subTest(command=command):
                reply = file_ops.handle(command)
                self.assertTrue(reply is None or 'bulamadım' in reply)
        self.assertTrue((self.downloads / 'rapor.pdf').exists())


    def test_undo_keeps_record_when_moved_file_was_replaced_or_edited(self):
        self.write(self.downloads, 'rapor.pdf', 'original')
        file_ops.handle('rapor dosyasını belgelere taşı')
        moved = self.documents / 'rapor.pdf'
        moved.write_text('user replacement', encoding='utf-8')
        self.assertIn('dokunmadım', file_ops.handle('son dosya işlemini geri al'))
        self.assertEqual(moved.read_text(encoding='utf-8'), 'user replacement')
        self.assertTrue(file_ops._undo_path('alice').exists())

    def test_undo_keeps_record_when_original_location_is_occupied(self):
        self.write(self.downloads, 'rapor.pdf', 'original')
        file_ops.handle('rapor dosyasını belgelere taşı')
        moved = self.documents / 'rapor.pdf'
        self.write(self.downloads, 'rapor.pdf', 'new occupant')
        self.assertIn('dokunmadım', file_ops.handle('son dosya işlemini geri al'))
        self.assertEqual(moved.read_text(encoding='utf-8'), 'original')
        self.assertEqual((self.downloads / 'rapor.pdf').read_text(encoding='utf-8'), 'new occupant')
        self.assertTrue(file_ops._undo_path('alice').exists())

    def test_undo_keeps_missing_destination_record_for_retry(self):
        self.write(self.downloads, 'rapor.pdf', 'original')
        file_ops.handle('rapor dosyasını belgelere taşı')
        (self.documents / 'rapor.pdf').unlink()
        self.assertIn('dokunmadım', file_ops.handle('son dosya işlemini geri al'))
        self.assertTrue(file_ops._undo_path('alice').exists())

    def test_undo_removes_only_completed_entries_from_partial_ledger(self):
        first = self.documents / 'first.txt'
        second = self.documents / 'second.txt'
        first.write_text('first', encoding='utf-8')
        second.write_text('second', encoding='utf-8')
        old_first = self.downloads / 'first.txt'
        old_second = self.downloads / 'second.txt'
        old_second.write_text('occupied', encoding='utf-8')
        file_ops._record([[str(first), str(old_first), file_ops._digest(first)],
                          [str(second), str(old_second), file_ops._digest(second)]], 'alice')
        self.assertIn('kısmen', file_ops.undo('alice'))
        self.assertTrue(old_first.exists())
        self.assertTrue(second.exists())
        remaining = __import__('json').loads(file_ops._undo_path('alice').read_text(encoding='utf-8'))
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0][0], str(second))


if __name__ == '__main__':
    unittest.main()
