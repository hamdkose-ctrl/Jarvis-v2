"""Kural regresyon testi: gerçek modeli ölçmez, model cevabı taklit edilir.

Veri: tests/data/yonlendirme_cumleleri.json. Model çağrılmaz; sınıflandırıcı modelin doğru
cevabı veri dosyasındaki 'model' alanıyla verilir ve Jarvis'in kendi kurallarının bu cevabı
bozup bozmadığı sınanır. 'bilinen_hata' işaretli satırlar bugün yanlış gidiyor: düzeltilince
bu test kırmızı olur ve işaretin kaldırılmasını ister, böylece set her zaman güncel kalır.

PR10c: `modules.router` kaldırıldı. "Jarvis'in kendi kuralı" artık canonical deterministik
katmandır (exact state gate + deterministic fast gate + Core plan). Bir cümleyi kural
claim'lemiyorsa karar modele devredilir ve taklit edilen `model` cevabı döner — yani taban
testin geçtiği geçirme (pass-through) semantiği birebir korunur.
"""
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from modules import brain_gates, learning
from modules.brain_contracts import ActiveContext

DATA = json.loads((Path(__file__).parent / 'data' / 'yonlendirme_cumleleri.json').read_text(encoding='utf-8'))

# Veri dosyasının sözlüğü (legacy router'ın intent adları): veri doğrulaması bu listeyi kullanır.
CORPUS_INTENTS = frozenset(
    'app_action code doc_summary doc_insight doc_convert translate doc_translate open_app open_url status '
    'screenshot volume feedback weather chat brightness media pc_control screen_analyze mail close_app work '
    'send_phone clarify task desktop_task handoff note'.split())
_ACTION_EQUIVALENT_CLAIMS = CORPUS_INTENTS - {'chat', 'clarify'}

# Canonical claim -> corpus sözlüğü. Yalnız kanonik sınırın ÜRETTİĞİ kararlar çevrilir.
_PLAN_TO_CORPUS = {'screen_analyze': 'screen_analyze', 'task': 'task', 'weather': 'weather',
                   'translate': 'translate', 'app_action': 'app_action',
                   'notes_read': 'note', 'notes_write': 'note', 'reminder': 'work',
                   'file_action': 'doc_summary', 'clarify': 'clarify'}
# Eski doc_* intent'leri hedef dosya seçicisini boş path ile yürütürdü; canonical sınır aynı
# durumda hedefi sorar. Bu satırlarda clarify, doc_* karşılığıdır.
_FILE_TARGET_QUESTION_STANDS_FOR = frozenset({'doc_summary', 'doc_insight', 'doc_convert', 'doc_translate'})
_FAST_TO_CORPUS = {'fast.system.status': 'status', 'fast.time.read': 'status', 'fast.date.read': 'status',
                   'fast.conversation.summary': 'chat'}

# Bu cümleleri canonical Brain claim'lemez; yanıtları hattın ilerisindeki adlı yürütücü sahiplerdir.
# Liste uzarsa yeni bir yürütücü sahibi doğmuştur; kısalırsa cümle canonical plana kavuşmuştur.
PRODUCTION_HANDLER_OWNED = frozenset({
    'ekran görüntüsü al',                       # engine_commands: ekran görüntüsü hızlı yolu
    'dosyayı ingilizceye çevir',                # canonical: dosya hedefi sorulur (FILE_TARGET_UNRESOLVED)
    'masaüstündeki raporu belgelere taşı',      # files/domain taşıma yürütücüsü
    'rapor hazırla', 'raporu hazırlar mısın',   # goal/job_front rapor yürütücüsü
    "ayarları aç ve bluetooth'u kapat",         # desktop_agent/Ayarlar domain yolu
    "excel'i açıp a1 hücresine 5 yaz",          # desktop_agent domain yolu
    'dönüştürür müsün',                         # belirsiz hedef: domain netleştirme
    'bu klasörü düzenler misin', 'masaüstünü düzenle',  # klasör düzenleme onay akışı
    'şu dosyayı silebilir misin', 'bu raporu kaydet', 'çöp kutusunu boşalt',
    "indirilenlerdeki pdf'leri listele", 'yeni bir klasör oluştur',  # nxapi dosya yürütücüleri
    "whatsapp'tan ahmet'e mesaj gönder",        # messaging domain akışı
    'bunu düzelt', 'onu sil',                   # zamirsiz hedef: bounded netleştirme
})


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
HOLDOUT_KNOWN_FAILURES = frozenset()


def _canonical_claim(text: str) -> str | None:
    """Canonical deterministik katmanın cümle için ÜRETTİĞİ karar; yoksa None (modele devir)."""
    owner, rid = "hamdi", "rid-routing"
    context = ActiveContext(owner=owner, request_id=rid)
    fast = brain_gates.deterministic_fast_gate(owner=owner, request_id=rid, text=text, active_context=context)
    if fast.matched:
        return _FAST_TO_CORPUS.get(fast.protocol)
    from modules import brain_core_map, brain_understanding
    semantic = brain_understanding.understand(owner=owner, request_id=rid, text=text,
                                              active_context=context, candidates=(), references=())
    plan = brain_core_map.core_plan(semantic.capability_hint, semantic.arguments)
    if plan is not None:
        intent, args = plan
        if intent == 'level_set':
            return args.get('property')
        if intent == 'file_action' and args.get('operation') == 'convert':
            return 'doc_convert'
        return _PLAN_TO_CORPUS.get(intent)
    if semantic.capability_hint == "files.read" and "file target unresolved" in semantic.ambiguities:
        return 'clarify'
    return None


def _route(row):
    # Kural bir karar üretiyorsa o geçerlidir; üretmiyorsa taklit edilen model cevabı geçerlidir.
    return _canonical_claim(row['metin']) or row['model']


def _task_equivalent_claim(claim: str | None) -> bool:
    """Legacy `task`, yalnız action sınıfındaki canonical planlarla eşdeğerdir."""
    return claim in _ACTION_EQUIVALENT_CLAIMS


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
        # Bugün bilinen hata yok; muhafız sözleşmesi sentetik işaret üzerinde doğrulanır.
        rows = [row for row in DATA['cumleler'] if row.get('bolum') == 'bekletilmis']
        marked = frozenset({rows[0]['metin']})
        with patch(__name__ + '._route', side_effect=lambda row: row['beklenen']), \
                patch(__name__ + '.HOLDOUT_KNOWN_FAILURES', marked):
            with self.assertRaisesRegex(AssertionError, 'HOLDOUT_KNOWN_FAILURES'):
                self.test_holdout_rule_regression_without_real_model()

    def test_a_marked_known_failure_is_not_counted_as_a_regression(self):
        # İşaret dürüst kalır: bilinen hata listedeyken kırmızıya dönüştürmez, ama liste boşaltılamaz.
        rows = [row for row in DATA['cumleler'] if row.get('bolum') == 'bekletilmis']
        original = _route
        with patch(__name__ + '._route', side_effect=lambda row: '__wrong__' if row is rows[0] else original(row)), \
                patch(__name__ + '.HOLDOUT_KNOWN_FAILURES', frozenset({rows[0]['metin']})):
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

    def test_task_equivalence_is_limited_to_action_claims(self):
        for claim in (None, 'chat', 'clarify', '__unknown__'):
            with self.subTest(claim=claim):
                self.assertFalse(_task_equivalent_claim(claim))
        for claim in ('task', 'weather', 'app_action', 'note', 'work', 'doc_summary'):
            with self.subTest(claim=claim):
                self.assertTrue(_task_equivalent_claim(claim))

    def test_sentences_reach_expected_route(self):
        for row in DATA['cumleler']:
            if row.get('bolum') == 'bekletilmis':
                continue
            with self.subTest(metin=row['metin']):
                got = _route(row)
                if row.get('bilinen_hata'):
                    self.assertNotEqual(got, row['beklenen'],
                                        'Bu bilinen hata düzelmiş; veri dosyasından bilinen_hata işaretini kaldır.')
                elif row['metin'].strip().casefold() in {t.casefold() for t in PRODUCTION_HANDLER_OWNED}:
                    # Canonical Brain bu cümleyi claim'lemez ya da dosya hedefini sorar; yanıt hattın
                    # ilerisindeki adlı yürütücüden gelir. Tek koşul: çelişen bir deterministik claim yok.
                    claim = _canonical_claim(row['metin'])
                    self.assertIn(claim, (None, 'clarify'), row['metin'])
                elif row['beklenen'] == 'task' and _task_equivalent_claim(_canonical_claim(row['metin'])):
                    # 'task' bu tabloda ortak hedef yürütücüsüdür; canonical sınır aynı cümleyi daha
                    # özel bir action Core planla (dosya/hatırlatma/araştırma) karşılıyorsa eşdeğerdir.
                    pass
                elif got == 'clarify' and row['beklenen'] in _FILE_TARGET_QUESTION_STANDS_FOR:
                    pass  # hedef dosya soruluyor: eski boş-path seçicisinin canonical karşılığı
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
            self.assertIn(row['beklenen'], CORPUS_INTENTS | {'chat'})
            self.assertIn(row['model'], CORPUS_INTENTS)
            self.assertIn(row.get('bolum', 'ayarlama'), ('ayarlama', 'bekletilmis'))
            if 'onay_gerekli' in row:
                self.assertIs(type(row['onay_gerekli']), bool,
                              'onay_gerekli yalnız JSON true/false olabilir.')
            if row.get('bolum') == 'bekletilmis':
                self.assertNotIn('bilinen_hata', row, 'Bekletilmiş satır kural regresyonuyla ölçülür, işaretlenmez.')

    def test_the_handler_owned_list_is_exactly_what_the_canonical_layer_does_not_claim(self):
        # Bu liste büyürse yeni bir cümle yürütücü sahibine kaçmış; küçülürse cümle canonical plana
        # kavuşmuş demektir. İkisi de bilinçli değişiklik ister, sessiz sürüklenme kabul edilmez.
        listed = {t.casefold() for t in PRODUCTION_HANDLER_OWNED}
        for row in DATA['cumleler']:
            if row.get('bolum') == 'bekletilmis' or row['model'] == row['beklenen']:
                continue
            text = row['metin'].strip().casefold()
            claim = _canonical_claim(row['metin'])
            if text in listed:
                self.assertIn(claim, (None, 'clarify'), f'{row["metin"]} artık canonical bir plan üretiyor')
            else:
                self.assertIsNotNone(claim, f'{row["metin"]} ne canonical plan ne de yürütücü sahibi listesinde')


if __name__ == '__main__':
    unittest.main()
