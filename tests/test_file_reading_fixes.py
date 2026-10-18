"""Dosya okuma ve aramada gerçek dosyalarla bulunan hatalar (17 Ekim 2026).

Okuma ve arama gerçek dosyalarla çalışır (read_document taklit edilmez); yalnız model çağrısı taklittir.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import docs, kb, translate


class Profile:
    def __init__(self, slug='deneme'):
        self.slug, self.data, self._id = slug, {}, 0

    def _new_id(self):
        self._id += 1
        return self._id

    def save(self):
        pass


class FileFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        p = patch.object(kb, 'ROOT', self.dir / 'kb'); p.start(); self.addCleanup(p.stop)
        self.profile = Profile()

    def path(self, name, data):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    # 1. Türkçe Windows kodlaması (cp1254) ve Not Defteri "Unicode" (UTF-16) metinleri harf kaybetmez
    def test_text_encodings_keep_turkish_letters(self):
        cases = {
            'cp1254.txt': 'Şirket ağır işçi çalıştırır. İĞÜ'.encode('cp1254'),
            'utf8.txt': 'Şirket ağır işçi çalıştırır. İĞÜ'.encode('utf-8'),
            'bom.txt': 'Şirket ağır işçi çalıştırır. İĞÜ'.encode('utf-8-sig'),
            'utf16.txt': 'Şirket ağır işçi çalıştırır. İĞÜ'.encode('utf-16'),
            'not.md': 'Şirket ağır işçi çalıştırır. İĞÜ'.encode('cp1254'),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertEqual(docs.read_document(str(self.path(name, data))), 'Şirket ağır işçi çalıştırır. İĞÜ')

    # 2. Türkçe Excel'in kaydettiği CSV (cp1254 + ';') MarkItDown'a gitmeden sütunlarıyla okunur
    def test_turkish_excel_csv_is_read_by_own_reader(self):
        csv = self.path('tablo.csv', 'Ürün;Fiyat\nÇay;30\nŞeker;45\n'.encode('cp1254'))
        with patch.object(docs, 'read_markitdown_isolated', side_effect=AssertionError('CSV MarkItDown\'a gitmemeli')):
            self.assertEqual(docs.read_document(str(csv)), 'Ürün | Fiyat\nÇay | 30\nŞeker | 45')

    def test_cp1254_text_is_found_by_search(self):
        kb.add(self.profile, str(self.path('not.txt', 'Gecikme cezası günlük binde iki. Şirket ağır işçi.'.encode('cp1254'))))
        self.assertEqual([h['name'] for h in kb.file_hits(self.profile, 'şirket ağır işçi')], ['not.txt'])

    def test_old_broken_text_entry_is_reread_on_next_add(self):
        path = self.path('eski.txt', 'Şirket ağır işçi.'.encode('cp1254'))
        with patch.object(docs, 'read_document', return_value='irket ar ii.'):   # düzeltmeden önceki okuma
            old = kb.add(self.profile, str(path))
        old.pop('v')                                                            # eski sürümün kaydı
        new = kb.add(self.profile, str(path))
        self.assertNotEqual(new['id'], old['id'])
        self.assertEqual([h['name'] for h in kb.file_hits(self.profile, 'şirket ağır')], ['eski.txt'])
        self.assertIs(kb.add(self.profile, str(path)), new)                     # değişmemiş dosya tekrar okunmaz

    # 3. Farklı klasörlerde aynı adlı dosyalar karışmaz
    def test_same_named_files_point_to_their_own_path(self):
        elma = self.path('x/rapor.txt', 'Elma fiyatı 10 TL'.encode())
        armut = self.path('y/rapor.txt', 'Armut fiyatı 20 TL'.encode())
        kb.add(self.profile, str(elma)); kb.add(self.profile, str(armut))
        self.assertEqual(kb.file_hits(self.profile, 'elma')[0]['path'], str(elma))
        self.assertEqual(kb.file_hits(self.profile, 'armut')[0]['path'], str(armut))

    # 5. ASCII yazım ve farklı söyleyişler arama yoluna girer; ilgisiz komutlar girmez
    def test_question_variations_reach_search(self):
        kb.add(self.profile, str(self.path('kira.txt', 'Aylık kira bedeli 15.000 TL'.encode())))
        asked = []
        with patch.object(kb, 'answer', side_effect=lambda p, q: asked.append(q) or 'CEVAP'):
            for q in ('kira bedeli hangi dosyadaydı?', 'kira bedeli hangi dosyadaydi', 'kira bedeli hangi pdf\'teydi',
                      'kira hangi belgede geçiyor', 'kira hangi dosyalarda var', 'dosyalarımda kira geçiyor mu',
                      'dosyalarimda kira geciyor mu', 'yukledigim belgelerde kira var mi', 'KİRA BEDELİ HANGİ DOSYADA',
                      'KIRA BEDELI HANGI DOSYADA'):
                with self.subTest(q):
                    self.assertEqual(kb.handle(kb._norm(q), self.profile), 'CEVAP')   # motordaki _tr_lower ile aynı
            for q in ('yüklediğim dosyayı özetle', 'hangi dosyadan bahsediyorsun', 'hangi dosyayı açayım',
                      'dosyalarımı göster', 'kira sözleşmesi hazırla'):
                with self.subTest(q):
                    self.assertIsNone(kb.handle(kb._norm(q), self.profile))

    # 6. "nerede yazıyordu": yalnız belgesi olan kullanıcıda ve cümlede aranacak konu belgede bulunuyorsa aramaya girer
    def test_where_written_questions_reach_search_only_with_matching_docs(self):
        asked = []
        with patch.object(kb, 'answer', side_effect=lambda p, q: asked.append(q) or 'CEVAP'):
            self.assertIsNone(kb.handle(kb._norm('kira bedeli nerede yazıyordu'), self.profile))   # belge yok
            kb.add(self.profile, str(self.path('kira.txt', 'Aylık kira bedeli 15.000 TL'.encode())))
            for q in ('kira bedeli nerede yazıyordu', 'kira bedeli nerde yaziyodu', 'KİRA NEREDE GEÇİYORDU',
                      'kira bedeli nerede yazıyor', 'kira bedeli nerede geciyodu'):
                with self.subTest(q):
                    self.assertEqual(kb.handle(kb._norm(q), self.profile), 'CEVAP')
            for q in ('nerede yazıyordu', 'zeytinyağı fiyatı nerede yazıyordu', 'kira nerede oturuyordu',
                      "Windows'ta başlangıç programlarını nereden kapatıyorduk", 'kira bedeli neydi'):
                with self.subTest(q):
                    self.assertIsNone(kb.handle(kb._norm(q), self.profile))     # sohbete düşer, uydurma yok

    def test_ascii_question_words_do_not_dilute_search(self):
        self.assertEqual(kb._match_query('kira hangi dosyadaydi'), '"kira"*')
        self.assertEqual(kb._match_query("kira hangi pdf'teydi"), '"kira"*')

    # 6. Metinsiz PDF'te yerel OCR komutu önerilir (OCR kendiliğinden çalışmaz)
    def test_scanned_pdf_message_suggests_local_ocr(self):
        from pypdf import PdfWriter
        w = PdfWriter(); w.add_blank_page(width=200, height=200)
        pdf = self.dir / 'taranmis.pdf'
        with open(pdf, 'wb') as f:
            w.write(f)
        with self.assertRaises(ValueError) as e:
            kb.add(self.profile, str(pdf))
        self.assertIn(f'"{pdf}" yerel OCR ile oku', str(e.exception))
        with self.assertRaisesRegex(ValueError, 'boş'):
            kb.add(self.profile, str(self.path('bos.txt', b'')))

    # 4. Uzun belge çevirisi sınırlı sayıda model çağrısı yapar ve kalanı açıkça söyler
    def test_long_translation_is_capped_and_says_what_is_missing(self):
        long = self.path('uzun.txt', (('Sözleşme maddesi. ' * 150 + '\n\n') * 200).encode())
        calls = []
        with patch.object(translate, 'ask', side_effect=lambda *a, **k: calls.append(1) or 'ÇEVİRİ: x\nNOTLAR: yok'):
            result = translate.translate_text_document(str(long), 'İngilizce')
        self.assertEqual(len(calls), translate.MAX_TEXT_PARTS)
        self.assertIn('karakter çevrilmedi', result)
        short = self.path('kisa.txt', 'Kısa metin.'.encode())
        with patch.object(translate, 'ask', return_value='ÇEVİRİ: Short text.\nNOTLAR: yok'):
            self.assertEqual(translate.translate_text_document(str(short), 'İngilizce'), 'Short text.')

    def test_failed_reread_keeps_old_searchable_record(self):
        f = self.path('degisen.txt', 'eski içerik kira'.encode())
        kb.add(self.profile, str(f))
        f.write_bytes(b'')                                   # yeni hâli okunamıyor (boş)
        with self.assertRaises(ValueError):
            kb.add(self.profile, str(f))
        self.assertTrue(kb.file_hits(self.profile, 'kira'))

    def test_large_excel_translation_stops_before_any_call(self):
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active
        for i in range(translate.MAX_EXCEL_BATCHES * 15 + 1):
            ws.append([f'metin {i}'])
        book = self.dir / 'buyuk.xlsx'; wb.save(book)
        with patch.object(translate, 'ask', side_effect=AssertionError('model çağrılmamalı')), \
             patch.object(translate.output, 'choose_excel_translation_path', side_effect=AssertionError('kayıt sorulmamalı')):
            self.assertIn('Hiçbir şey çevrilmedi', translate.translate_excel_document(str(book), 'İngilizce'))


if __name__ == '__main__':
    unittest.main()


class ExcelNanTests(unittest.TestCase):
    def test_empty_cells_and_unsaved_formula_are_not_nan(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        from unittest.mock import patch
        from modules import docs
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Hesap"
        ws.append(["Ad", "Tutar"])
        ws.append(["a", 10])
        ws["A5"] = "Toplam"
        ws["B5"] = "=SUM(B2:B3)"      # openpyxl sonucu kaydetmez
        path = Path(tempfile.mkdtemp()) / "f.xlsx"
        wb.save(path)
        # MarkItDown'ın pandas çıktısı taklit edilir (gerçek alt süreç Windows CI'da paketi yavaşlatıyor)
        fake = ("## Hesap\n\n| Ad | Tutar |\n| --- | --- |\n| a | 10 |\n| NaN | NaN |\n| NaN | NaN |\n| Toplam | NaN |\n")
        with patch.object(docs, 'read_markitdown_isolated', return_value=fake):
            text = docs.read_document(str(path))
        self.assertNotIn("NaN", text)
        self.assertIn("Hesap!B5", text)
        self.assertIn("kayıtlı sonucu yok", text)
