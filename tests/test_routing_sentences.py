"""Kural regresyon testi: gerçek modeli ölçmez, model cevabı taklit edilir.

Veri: tests/data/yonlendirme_cumleleri.json. Model çağrılmaz; sınıflandırıcı modelin doğru
cevabı veri dosyasındaki 'model' alanıyla verilir ve Jarvis'in kendi kurallarının bu cevabı
bozup bozmadığı sınanır. 'bilinen_hata' işaretli satırlar bugün yanlış gidiyor: düzeltilince
bu test kırmızı olur ve işaretin kaldırılmasını ister, böylece set her zaman güncel kalır.
"""
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from modules import learning, router

DATA = json.loads((Path(__file__).parent / 'data' / 'yonlendirme_cumleleri.json').read_text(encoding='utf-8'))

# Referans: main fdfd04756042396616a22bd57ebaa9827afe43aa, 48/49 doğru.
# Eşik oran değil, bu sabit cümle kümesindeki bilinen hatalar dışındaki başarısızlıklardır.
# Yeni cümleler yalnız ölçülür; ekleme/silme eski cümlelerin korumasını değiştirmez.
# Seti güncelleyen geliştirici, PR inceleyicisiyle sonuçları doğrulayıp yeni cümleyi
# referansa, geçmiyorsa bilinen hatalara ekler; silineni iki listeden çıkarır.
# Düzelen bilinen hata listeden kaldırılır. Listeler test çalışırken otomatik üretilmez.
HOLDOUT_BASELINE_SENTENCES = frozenset({
    "Beni bi güldür ya.",
    "mail göndermek nasıl çalışır?",
    "Chrome'da yer imlerini dışa aktarmak nasıl yapılıyordu?",
    "Borsa emri verince hemen gerçekleşir mi?",
    "maili geri cagirmak mumkun mu",
    "bi mail yazarken konu basligi ne kadar onemli",
    "Sence masaüstünü klasörlere ayırmak mantıklı mı?",
    "Bugünkü piyasada volatilite ne demek?",
    "Tarayıcı çerezleri tam olarak ne tutuyor?",
    "Görev çubuğunu gizlemek performansı etkiler mi?",
    "Mümkünse takvim bloklama yöntemini açıklar mısın?",
    "Toplantı notu işi... iyi not nasıl tutulur?",
    "mail yazacağım ama kısa mı uzun mu olsun sence",
    "Bana iki seçenek sunsan, dosyaları tarihe göre mi konuya göre mi ayırırsın?",
    "Ben “bunu ara” dersem sen neyi aradığımı nasıl anlarsın?",
    "İki dosya aynı isimdeyse hangisini seçersin?",
    "bu mailli işlerde taslakla gonder arasındaki fark neydi",
    "Bluetooth'u kapat.",
    "rica etsem gece ışığını açar mısın",
    "indirmeler klasörünü aç",
    "Bugün İstanbul'da yağışla ilgili son durumu bul.",
    "rica etsem resmi kaynaktan doğrular mısın",
    "Şu linkte ne anlatılıyor, kısa özet çıkar.",
    "şu makalenin yayın tarihini ve yazarını kontrol et",
    "Bu PDF'yi aç, ilk iki sayfayı özetle.",
    "Rica etsem bu metindeki yazım hatalarını düzeltebilir misin?",
    "Şunu bi toparla, tekrar eden paragrafları da temizle.",
    "Rica etsem proje klasörünün boyutunu hesaplar mısın?",
    "Arşiv klasörünü ZIP'le ve masaüstüne koy.",
    "bu maile kısa bi cevap taslağı hazırla",
    "Bu maili taslaklara kaydet, gönderme.",
    "En yeni okunmamış e-postayı bul, aç ve kısaca özetle.",
    "Cuma öğleden sonraya bir saat çalışma bloğu koy.",
    "Bu akşamki etkinliğin yerini göster.",
    "bu haberi başka kaynaklar da vermiş mi kontrol et",
    "Son haftadaki teknoloji haberlerini konu başlıklarına ayır.",
    "Bu şirketin son bilancosundaki gelir ve kârı çıkar.",
    "WhatsApp'ta sabitlenmiş sohbetleri göster.",
    "Bu konuyu öğrenmem için üç kaynak bul, sonra bana çalışma sırası çıkar.",
    "Oraya koy.",
    "İlkini yap.",
    "şey var ya onu indir",
    "bu klasörü sil",
    "cevabi gonder",
    "Mesajı gönder.",
    "Son maile evet de.",
    "Bunu satın al.",
    "Şunu bi halletsen?",
    "Şu ikisinden birini sil.",
})
HOLDOUT_KNOWN_FAILURES = frozenset({
    "bu mailli işlerde taslakla gonder arasındaki fark neydi",
})


def _route(row):
    answer = json.dumps({'intent': row['model'], 'args': {}})
    return router.classify(row['metin'], lambda *_: answer)['intent']


class _Profile:
    def __init__(self, rule):
        self.data = {'rules': [rule]}


class RoutingSentenceTests(unittest.TestCase):
    def test_new_failing_holdout_sentence_is_only_measured(self):
        rows = [row for row in DATA['cumleler'] if row.get('bolum') == 'bekletilmis']
        added = dict(rows[0], metin='Yeni bekletilmiş örnek: henüz doğru yönlenmiyor.')
        original = _route
        with patch.dict(DATA, cumleler=rows + [added]), patch(
                __name__ + '._route', side_effect=lambda row: '__wrong__' if row is added else original(row)):
            self.test_holdout_rule_regression_without_real_model()

    def test_passing_additions_cannot_hide_old_sentence_regression(self):
        rows = [row for row in DATA['cumleler'] if row.get('bolum') == 'bekletilmis']
        broken = rows[0]['metin']
        added = [dict(rows[0], metin=f'Yeni başarılı bekletilmiş örnek {i}') for i in range(100)]
        original = _route
        def route(row):
            if row['metin'] == broken:
                return '__wrong__'
            return row['beklenen'] if row in added else original(row)
        with patch.dict(DATA, cumleler=rows + added), patch(__name__ + '._route', side_effect=route):
            with self.assertRaises(AssertionError):
                self.test_holdout_rule_regression_without_real_model()

    def test_removing_passing_holdout_sentence_does_not_lower_threshold(self):
        rows = [row for row in DATA['cumleler'] if row.get('bolum') == 'bekletilmis']
        with patch.dict(DATA, cumleler=rows[1:]):
            self.test_holdout_rule_regression_without_real_model()

    def test_fixed_holdout_failure_requires_marker_removal(self):
        with patch(__name__ + '._route', side_effect=lambda row: row['beklenen']):
            with self.assertRaisesRegex(AssertionError, 'HOLDOUT_KNOWN_FAILURES'):
                self.test_holdout_rule_regression_without_real_model()

    def test_rule_regression_guard_rejects_holdout_drop(self):
        with patch(__name__ + '._route', return_value='__wrong__'):
            with self.assertRaises(AssertionError):
                self.test_holdout_rule_regression_without_real_model()

    def test_rule_data_validation_rejects_invalid_approval_values(self):
        for value in (None, 0, 1, 'true', 'false', [], {}):
            row = dict(DATA['cumleler'][0], onay_gerekli=value)
            with self.subTest(value=value), patch.dict(DATA, cumleler=[row]):
                with self.assertRaises(AssertionError):
                    self.test_data_is_well_formed()

    def test_rule_regression_guard_rejects_one_more_miss(self):
        rows = [row for row in DATA['cumleler'] if row.get('bolum') == 'bekletilmis']
        for total, correct in ((49, 47), (98, 95)):
            sample = [rows[0]] * total
            answers = [rows[0]['beklenen']] * correct + ['__wrong__'] * (total - correct)
            with self.subTest(total=total), patch.dict(DATA, cumleler=sample):
                with patch(__name__ + '._route', side_effect=answers):
                    with self.assertRaises(AssertionError):
                        self.test_holdout_rule_regression_without_real_model()

    def test_rule_data_validation_accepts_boolean_approval_values(self):
        for value in (False, True):
            with self.subTest(value=value), patch.dict(
                    DATA, cumleler=[dict(DATA['cumleler'][0], onay_gerekli=value)]):
                self.test_data_is_well_formed()

    def test_sentences_reach_expected_route(self):
        for row in DATA['cumleler']:
            if row.get('bolum') == 'bekletilmis':
                continue
            with self.subTest(metin=row['metin']):
                got = _route(row)
                if row.get('bilinen_hata'):
                    self.assertNotEqual(got, row['beklenen'],
                                        'Bu bilinen hata düzelmiş; veri dosyasından bilinen_hata işaretini kaldır.')
                else:
                    self.assertEqual(got, row['beklenen'])

    def test_holdout_rule_regression_without_real_model(self):
        # Kural regresyonu; sınıflandırıcı model çağrılmaz ve kalitesi ölçülmez.
        rows = [row for row in DATA['cumleler'] if row.get('bolum') == 'bekletilmis']
        wrong = [row['metin'] for row in rows if _route(row) != row['beklenen']]
        self.assertTrue(rows, 'Bekletilmiş kural regresyon seti boş olamaz.')
        current = {row['metin'] for row in rows}
        baseline = current & HOLDOUT_BASELINE_SENTENCES
        self.assertTrue(baseline, 'Referans cümlelerin tamamı kayıp; listeleri PR incelemesiyle güncelle.')
        regressions = set(wrong) & baseline - HOLDOUT_KNOWN_FAILURES
        self.assertFalse(regressions, f'Önceden geçen cümlelerde kural regresyonu: {sorted(regressions)}')
        fixed = baseline & HOLDOUT_KNOWN_FAILURES - set(wrong)
        self.assertFalse(fixed, f'Bu bilinen hatalar düzelmiş; HOLDOUT_KNOWN_FAILURES listesinden kaldır: {sorted(fixed)}')
        print(f"\nBekletilmiş cümle seti: {len(rows) - len(wrong)}/{len(rows)} doğru"
              + (f"; yanlış: {wrong}" if wrong else ''))

    def test_taught_rules_reach_matching_questions(self):
        for row in DATA['kurallar']:
            with self.subTest(kural=row['kural'], soru=row['soru']):
                got = bool(learning.rules_prompt(_Profile(row['kural']), row['soru']))
                if row.get('bilinen_hata'):
                    self.assertNotEqual(got, row['yuklenmeli'],
                                        'Bu bilinen hata düzelmiş; veri dosyasından bilinen_hata işaretini kaldır.')
                else:
                    self.assertEqual(got, row['yuklenmeli'])

    def test_data_is_well_formed(self):
        self.assertLessEqual(HOLDOUT_KNOWN_FAILURES, HOLDOUT_BASELINE_SENTENCES)
        texts = [row['metin'].casefold() for row in DATA['cumleler']]
        self.assertEqual(len(texts), len(set(texts)), 'Aynı cümle iki kez yazılmış.')
        for row in DATA['cumleler']:
            self.assertIn(row['beklenen'], router._INTENTS | {'chat'})
            self.assertIn(row['model'], router._INTENTS)
            self.assertIn(row.get('bolum', 'ayarlama'), ('ayarlama', 'bekletilmis'))
            if 'onay_gerekli' in row:
                self.assertIs(type(row['onay_gerekli']), bool,
                              'onay_gerekli yalnız JSON true/false olabilir.')
            if row.get('bolum') == 'bekletilmis':
                self.assertNotIn('bilinen_hata', row, 'Bekletilmiş satır kural regresyonuyla ölçülür, işaretlenmez.')


if __name__ == '__main__':
    unittest.main()
