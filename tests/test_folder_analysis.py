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
        self.assertIn('hesap şifreleri.txt', out)                          # gizli: adından
        self.assertIn('not.txt', out.split('açmadığım')[1])                # gizli: içeriğinden (IBAN)
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


if __name__ == '__main__':
    unittest.main()
