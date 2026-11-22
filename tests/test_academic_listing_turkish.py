"""Akademik liste Türkçeleşir (kullanıcı geri bildirimi, 22 Kasım 2026).

Kullanıcı canlı cevabı görünce: "bu araştırma sitesi İngilizce, ben ne anlarım; siteyi de
bilmiyorum". Liste artık Türkçe başlık+özet verir ve arXiv'ın ne olduğunu bir cümleyle
söyler. Bağlantılar **modelden gelmez**: kaydın kendi adresi yazılır, uydurma adres
üretilemez. Model yoksa/JSON bozuksa liste İngilizce kalır ama Türkçe tanıtım eklenir.
"""
import unittest
from unittest.mock import patch

from modules import task_results
from modules.task_workers import academic_listing

ROWS = [
    {'provider': 'arxiv', 'title': 'Dilated Neighborhood Attention', 'url': 'https://arxiv.org/abs/2209.15001v3',
     'published': '2022-09-29', 'snippet': 'We propose a hierarchical transformer.'},
    {'provider': 'arxiv', 'title': 'Second paper', 'url': 'https://arxiv.org/abs/2105.02723v1',
     'published': '2021-05-06', 'snippet': 'Second abstract.'},
]

TURKISH = ('{"items":[{"no":1,"baslik":"Genişletilmiş Komşuluk Dikkati",'
           '"ozet":"Hiyerarşik bir dönüştürücü öneriyor."},'
           '{"no":2,"baslik":"İkinci makale","ozet":"İkinci özet."}]}')


class TurkishListingTests(unittest.TestCase):
    def listing(self, answer=None, error=None, translate=True):
        with patch('modules.llm.ask', return_value=answer, side_effect=error):
            return academic_listing([dict(row) for row in ROWS], 'Yapay zeka makaleleri araştır',
                                    translate=translate)

    def test_titles_and_summaries_are_turkish_with_real_links(self):
        out = self.listing(TURKISH)
        self.assertIn('Genişletilmiş Komşuluk Dikkati', out['text'])
        self.assertIn('Hiyerarşik bir dönüştürücü öneriyor.', out['text'])
        self.assertIn('https://arxiv.org/abs/2209.15001v3', out['text'])
        self.assertNotIn('Dilated Neighborhood Attention', out['text'])
        self.assertIn('Özet: Hiyerarşik bir dönüştürücü öneriyor.', out['text'])
        self.assertIn('· arXiv', out['text'])   # çevrilen kayıt işaretli
        self.assertTrue(out['academic_listing'])
        task_results.check('research', out)          # sözleşme bozulmadı

    def test_model_down_keeps_english_list_but_explains_the_site(self):
        out = self.listing(error=RuntimeError('model yok'))
        self.assertIn('Dilated Neighborhood Attention', out['text'])
        self.assertIn('preprint', out['text'])
        self.assertIn('İngilizce', out['text'])
        task_results.check('research', out)

    def test_hallucinated_or_incomplete_answers_are_rejected(self):
        bad_answers = [
            '{"items":[{"no":1,"baslik":"Uydurma","ozet":"bkz https://evil.test"}]}',          # eksik + adres
            '{"items":[{"no":1,"baslik":"A","ozet":"x"},{"no":2,"baslik":"B","ozet":"y"},'
            '{"no":3,"baslik":"C","ozet":"z"}]}',                                             # fazla kayıt
            '{"items":[{"no":1,"baslik":"A","ozet":"x"},{"no":1,"baslik":"B","ozet":"y"}]}',  # tekrar no
            '{"items":[]}',
            'JSON değil',
            '{"items":[{"no":1,"baslik":"","ozet":""},{"no":2,"baslik":"B","ozet":"y"}]}',
        ]
        for answer in bad_answers:
            out = self.listing(answer)
            self.assertIn('Dilated Neighborhood Attention', out['text'], answer)   # İngiliz liste korunur
            self.assertNotIn('evil.test', out['text'], answer)
            task_results.check('research', out)

    def test_translation_is_opt_in(self):
        """Varsayılan davranış aynı kalır (mevcut sözleşme/testler bozulmaz)."""
        out = self.listing(TURKISH, translate=False)
        self.assertIn('Dilated Neighborhood Attention', out['text'])
        with patch('modules.llm.ask', side_effect=AssertionError('model çağrılmamalı')):
            out = academic_listing([dict(row) for row in ROWS], 'araştır')
        self.assertEqual(out['state'], 'done')


if __name__ == '__main__':
    unittest.main()
