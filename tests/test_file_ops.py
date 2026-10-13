"""Tek dosya işlemleri gerçek (geçici) klasörlerde denenir; kullanıcının dosyalarına dokunulmaz."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_ops, files


class FileOpsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
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
        self.assertIn('yok', file_ops.handle('son dosya işlemini geri al', 'bob'))
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


if __name__ == '__main__':
    unittest.main()
