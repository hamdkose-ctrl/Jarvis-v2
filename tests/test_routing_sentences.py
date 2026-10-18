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

# main fdfd04756042396616a22bd57ebaa9827afe43aa: 48/49 doğru.
# Sabit sayı yerine tam kesir: set büyüyünce başarı oranı korunur, yuvarlama yoktur.
HOLDOUT_BASELINE_CORRECT = 48
HOLDOUT_BASELINE_TOTAL = 49


def _route(row):
    answer = json.dumps({'intent': row['model'], 'args': {}})
    return router.classify(row['metin'], lambda *_: answer)['intent']


class _Profile:
    def __init__(self, rule):
        self.data = {'rules': [rule]}


class RoutingSentenceTests(unittest.TestCase):
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
        correct = len(rows) - len(wrong)
        self.assertGreaterEqual(
            correct * HOLDOUT_BASELINE_TOTAL, len(rows) * HOLDOUT_BASELINE_CORRECT,
            f'Kural regresyonu: {correct}/{len(rows)} doğru; eşik 48/49. Yanlış: {wrong}')
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

