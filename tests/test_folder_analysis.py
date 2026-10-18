"""Klasör analizi gerçek dosyalarla (okuma, özet değeri, arama dizini gerçek); yalnız model çağrısı taklittir."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import folder_analysis as fa, kb, nxapi


class Profile:
    def __init__(self):
        self.slug, self.data, self._id = 'deneme', {}, 0

    def _new_id(self):
        self._id += 1
        return self._id

    def save(self):
        pass


def _docx(path, text):
    from docx import Document
    d = Document(); d.add_paragraph(text); d.save(path)


class FolderAnalysisTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        for name, value in (('HOME', self.home), ('FILES_DIR', self.home / 'Documents' / 'Jarvis Dosyaları')):
            p = patch.object(nxapi, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(kb, 'ROOT', self.home / 'kb'); p.start(); self.addCleanup(p.stop)
        self.dl = self.home / 'Downloads'; self.dl.mkdir()
        self.profile = Profile()

    def write(self, rel, text, enc='utf-8'):
        p = self.dl / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode(enc))
        return p

    def fill(self):
        _docx(self.dl / 'kira sözleşmesi.docx', 'Aylık kira bedeli 15.000 TL. Kira artışı yılda bir yapılır. Kira bedeli peşin.')
        (self.dl / 'kopya.docx').write_bytes((self.dl / 'kira sözleşmesi.docx').read_bytes())
        self.write('proje/kira notu.txt', 'Kira bedeli için ev sahibiyle konuşuldu. Kira artışı kabul.', 'cp1254')
        self.write('proje/maliyet.csv', 'Kalem;Tutar\nÇimento;300\nÇimento nakliye;50\n', 'cp1254')
        self.write('bozuk.docx', 'zip değil')
        self.write('bos.txt', '')
        self.write('hesap şifreleri.txt', 'gmail: 1234')
        self.write('not.txt', 'IBAN TR12 0006 1000 0000 1234 5678 90 kira ödemesi')
        self.write('a/b/c/derin.txt', 'çok derindeki kira')
        (self.dl / 'foto.png').write_bytes(b'\x89PNG\r\n\x1a\n')

    def test_report_from_real_files(self):
        self.fill()
        prompts = []
        with patch('modules.llm.ask', side_effect=lambda q, **k: prompts.append(q) or 'Klasör ev kirası ve inşaat maliyetiyle ilgili.'):
            out = fa.analyze(self.profile, self.dl)
        self.assertEqual(len(prompts), 1)                                  # en çok bir model çağrısı
        self.assertIn('Ne hakkında: Klasör ev kirası', out)
        self.assertIn('kopya.docx = kira sözleşmesi.docx', out)            # birebir aynı dosya
        self.assertRegex(out, r'bozuk\.docx: .*bozuk')                     # okunamayan + nedeni
        self.assertIn('bos.txt: metin yok', out)
        self.assertIn('hesap şifreleri.txt', out.split('hiç açmadığım')[1].split('İçinde gizli')[0])   # gizli: adından, hiç açılmaz
        self.assertIn('not.txt', out.split('İçinde gizli bilgi')[1])       # gizli: içeriğinden (IBAN), kontrol için okundu
        self.assertIn('1 alt klasöre inmedim', out)                        # derinlik sınırı
        self.assertIn('1 dosyanın türü okunmuyor', out)                    # png yalnız sayıldı
        self.assertRegex(out, r'• kira[^\n]*kira sözleşmesi\.docx[^\n]*proje/kira notu\.txt')
        sent = prompts[0]
        for secret in ('1234', 'TR12', 'derindeki'):
            self.assertNotIn(secret, sent)
        self.assertIn('Çimento', sent)                                     # cp1254 CSV doğru okundu
        hits = [h['name'] for h in kb.file_hits(self.profile, 'kira bedeli')]
        self.assertIn('kira notu.txt', hits)                               # sonra arama çalışır
        self.assertFalse(kb.file_hits(self.profile, 'gmail'))              # gizli dosya dizine girmez

    def test_model_failure_still_gives_report(self):
        self.fill()
        with patch('modules.llm.ask', side_effect=RuntimeError('429')):
            out = fa.analyze(self.profile, self.dl)
        self.assertIn('genel özetini yapay zekâdan alamadım', out)
        self.assertIn('Birebir aynı dosyalar', out)

    def test_read_limit_is_reported(self):
        for i in range(fa.MAX_READ_FILES + 10):
            self.write(f'not{i:02}.txt', f'Toplantı {i} notu')
        with patch('modules.llm.ask', return_value='Toplantı notları klasörü, ayrıntı yok.'):
            out = fa.analyze(self.profile, self.dl)
        self.assertIn('10 belgeyi sınır nedeniyle okumadım', out)
        self.assertEqual(len(kb._docs(self.profile)), fa.MAX_READ_FILES)

    def test_outside_folder_and_symlink(self):
        outside = tempfile.TemporaryDirectory(); self.addCleanup(outside.cleanup)
        Path(outside.name, 'gizli.txt').write_text('dış klasör', encoding='utf-8')
        self.assertIn('erişemiyorum', fa.analyze(self.profile, Path(outside.name)))
        self.write('ic.txt', 'iç dosya iç dosya')
        try:
            (self.dl / 'bag').symlink_to(outside.name, target_is_directory=True)
        except OSError:
            self.skipTest('sembolik bağ oluşturulamadı')
        with patch('modules.llm.ask', return_value='İç dosyalar klasörü, kısa bir not.'):
            out = fa.analyze(self.profile, self.dl)
        self.assertIn('1 dosya var', out)

    def test_phrases(self):
        (self.home / 'Desktop').mkdir(); (self.dl / 'Proje').mkdir()
        yes = {'indirilenler klasörünü incele': self.dl, 'indirilenler klasorunu incele': self.dl,
               'indirilenlerde ne var': self.dl, 'indirilenler ne hakkında': self.dl,
               'masaüstümde neler var': self.home / 'Desktop', 'masaustunde ne var': self.home / 'Desktop',
               'indirilenlerdeki proje klasörünü incele': self.dl / 'Proje', 'indirilenler klasörünü özetle': self.dl,
               'toplantı notları için indirilenler klasörünü incele': self.dl,
               'açıklamalı belgeler klasörü ne hakkında': self.home / 'Documents'}
        (self.home / 'Documents').mkdir()
        for q, want in yes.items():
            with self.subTest(q):
                self.assertEqual(fa.target(kb._norm(q)), want)
        for q in ('indirilenleri düzenle', 'indirilenlerdeki rapor dosyasını özetle', 'indirilenlerde kira geçiyor mu',
                  'bugün ne var', 'indirilenler klasörünü aç', 'bu belgeyi incele', 'evde neler var', 'indirilenleri izle',
                  'masaüstünü temizle', 'indirilenleri açar mısın', 'masaüstünü düzenler misin', 'resim nedir', 'dosyalarımı göster', 'videolar klasöründe ne var'):
            with self.subTest(q):
                self.assertIsNone(fa.target(kb._norm(q)))

    # --- GPT incelemesi (madde 4-9): gerçek klasör düzenleriyle ---
    def test_onedrive_redirected_folder_wins_over_empty_stub(self):
        (self.home / 'Desktop').mkdir()                                    # boş kalıntı
        real = self.home / 'OneDrive' / 'Desktop'; real.mkdir(parents=True)
        (real / 'a.txt').write_text('gerçek dosya', encoding='utf-8')
        self.assertEqual(fa.target(kb._norm('masaüstümde ne var')), real)

    def test_named_subfolder_not_found_does_not_expand(self):
        (self.dl / 'Proje Dosyaları').mkdir(); (self.dl / 'baska.txt').write_text('x', encoding='utf-8')
        self.assertEqual(fa.target(kb._norm('indirilenlerdeki proje dosyaları klasörünü incele')), self.dl / 'Proje Dosyaları')
        self.assertIsNone(fa.target(kb._norm('indirilenlerdeki gizli proje klasörünü incele')))
        with patch('modules.llm.ask', side_effect=AssertionError('model çağrılmamalı')):
            out = fa.handle(kb._norm('indirilenlerdeki gizli proje klasörünü incele'), self.profile)
        self.assertIn("'proje' adlı bir klasör bulamadım", out)
        self.assertNotIn('baska.txt', out)

    def test_two_folder_phrase_goes_to_named_folder(self):
        (self.home / 'Desktop').mkdir(); (self.home / 'Documents').mkdir()
        self.assertEqual(fa.target(kb._norm('masaüstündeki belgeler klasörünü incele')), self.home / 'Documents')

    def test_secret_files_are_not_hashed_and_wording_is_exact(self):
        (self.dl / 'sifre1.txt').write_text('aynı', encoding='utf-8'); (self.dl / 'sifre2.txt').write_text('aynı', encoding='utf-8')
        (self.dl / 'kayit1.txt').write_text('IBAN TR12 0006 1000 0000 1234 5678 90', encoding='utf-8')
        (self.dl / 'kayit2.txt').write_text('IBAN TR12 0006 1000 0000 1234 5678 90', encoding='utf-8')
        with patch.object(fa, '_sha', side_effect=AssertionError('gizli dosya özet için açılmamalı')), \
             patch('modules.llm.ask', return_value='x' * 30):
            out = fa.analyze(self.profile, self.dl)
        self.assertNotIn('Birebir aynı', out)
        self.assertIn('hiç açmadığım 2 dosya', out)
        self.assertIn('kontrol için bilgisayarda açıldı', out)

    def test_file_vanishing_during_scan_does_not_drop_report(self):
        self.write('a.txt', 'kira kira'); self.write('b.txt', 'kira kira')
        real = Path.stat
        def flaky(self_, *a, **k):
            if self_.name == 'a.txt' and k.get('follow_symlinks', True):
                flaky.calls += 1
                if flaky.calls == 3:        # tarama is_file, sıralama exists, sıralama stat: sonuncusunda dosya kayboldu
                    raise FileNotFoundError('silindi')
            return real(self_, *a, **k)
        flaky.calls = 0
        with patch.object(Path, 'stat', flaky), patch('modules.llm.ask', return_value='x' * 30):
            out = fa.analyze(self.profile, self.dl)
        self.assertIn('klasöründe', out)                          # rapor düşmedi, kalan dosya sürdü

    def test_report_paths_use_forward_slashes(self):
        self.write('proje/kira notu.txt', 'kira kira bedeli'); self.write('proje/kira 2.txt', 'kira kira bedeli')
        with patch('modules.llm.ask', return_value='x' * 30):
            self.assertIn('proje/kira notu.txt', fa.analyze(self.profile, self.dl))

    def test_junction_like_dir_outside_allowed_tree_is_skipped(self):
        outside = tempfile.TemporaryDirectory(); self.addCleanup(outside.cleanup)
        Path(outside.name, 'dis.txt').write_text('dış', encoding='utf-8')
        (self.dl / 'kisayol').mkdir(); self.write('ic.txt', 'iç iç')
        real = nxapi.allowed
        with patch.object(nxapi, 'allowed', side_effect=lambda p: None if Path(p).name == 'kisayol' else real(p)), \
             patch('modules.llm.ask', return_value='x' * 30):
            self.assertIn('1 dosya var', fa.analyze(self.profile, self.dl))


if __name__ == '__main__':
    unittest.main()
