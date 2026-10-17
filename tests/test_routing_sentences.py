"""Gerçek kullanım cümleleriyle yönlendirme ve kural yükleme regresyon seti.

Veri: tests/data/yonlendirme_cumleleri.json. Model çağrılmaz; sınıflandırıcı modelin doğru
cevabı veri dosyasındaki 'model' alanıyla verilir ve Jarvis'in kendi kurallarının bu cevabı
bozup bozmadığı sınanır. 'bilinen_hata' işaretli satırlar bugün yanlış gidiyor: düzeltilince
bu test kırmızı olur ve işaretin kaldırılmasını ister, böylece set her zaman güncel kalır.
"""
import json
import unittest
from pathlib import Path

from modules import learning, router

DATA = json.loads((Path(__file__).parent / 'data' / 'yonlendirme_cumleleri.json').read_text(encoding='utf-8'))


def _route(row):
    answer = json.dumps({'intent': row['model'], 'args': {}})
    return router.classify(row['metin'], lambda *_: answer)['intent']


class _Profile:
    def __init__(self, rule):
        self.data = {'rules': [rule]}


class RoutingSentenceTests(unittest.TestCase):
    def test_sentences_reach_expected_route(self):
        for row in DATA['cumleler']:
            with self.subTest(metin=row['metin']):
                got = _route(row)
                if row.get('bilinen_hata'):
                    self.assertNotEqual(got, row['beklenen'],
                                        'Bu bilinen hata düzelmiş; veri dosyasından bilinen_hata işaretini kaldır.')
                else:
                    self.assertEqual(got, row['beklenen'])

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


if __name__ == '__main__':
    unittest.main()
