"""Model çöktüğünde akademik istek boş ret mesajıyla düşmesin.

Canlı kusur (22 Kasım 2026 21:23): "Yapay zeka makaleleri araştır" -> Gemini Brain
sözleşmesinden, Groq çağrıdan döndü; kullanıcı liste beklerken
"İstenen hedefi veya işlem bilgilerini güvenli biçimde doğrulayamadım" aldı.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from pathlib import Path

from modules import core_brain_adapter

ROW = {'provider': 'crossref', 'title': 'Ortodontide Yapay Zeka Kullanımı',
       'url': 'https://doi.org/10.70269/x', 'published': '2026-06',
       'snippet': 'Ortodontide yapay zeka uygulamaları.'}


class AcademicOutageAnswerTests(unittest.TestCase):
    def test_academic_request_is_answered_without_a_model(self):
        with patch('modules.task_workers.search_academic_rows', return_value=[ROW]) as search:
            text = core_brain_adapter._academic_outage_answer('Yapay zeka makaleleri araştır')
        self.assertIsNotNone(text)
        self.assertIn('Bulduğum akademik kaynaklar', text)
        self.assertIn('Ortodontide Yapay Zeka Kullanımı', text)
        self.assertIn('https://doi.org/10.70269/x', text)   # bağlantı kaydın kendi adresi
        search.assert_called_once()

    def test_news_request_does_not_take_this_path(self):
        """Haber hattı kendi doğrulamasını ister; burada yalnız makale listesi karşılanır."""
        self.assertIsNone(core_brain_adapter._academic_outage_answer(
            'Yapay zeka hakkında son dakika haberleri araştır'))

    def test_unrelated_request_is_untouched(self):
        self.assertIsNone(core_brain_adapter._academic_outage_answer('ekran parlaklığını artır'))

    def test_empty_result_keeps_the_old_refusal(self):
        with patch('modules.task_workers.search_academic_rows', return_value=[]):
            self.assertIsNone(core_brain_adapter._academic_outage_answer('Yapay zeka makaleleri araştır'))

    def test_search_failure_is_soft(self):
        with patch('modules.task_workers.search_academic_rows', side_effect=RuntimeError('ağ yok')):
            self.assertIsNone(core_brain_adapter._academic_outage_answer('Yapay zeka makaleleri araştır'))

    def test_turkish_rows_come_first_in_one_place(self):
        """Arama kuralı tek tanım: Türkçe kaynak önce, arXiv sonra, tekrar yok."""
        turkce = [dict(ROW, url='https://doi.org/10.1/tr')]
        arxiv = [dict(ROW, provider='arxiv', url='https://arxiv.org/abs/1'),
                 dict(ROW, provider='arxiv', url='https://doi.org/10.1/tr')]
        with patch('modules.research_providers.search_turkish', return_value=turkce), \
             patch('modules.research_providers.search_academic', return_value=arxiv):
            rows = __import__('modules.task_workers', fromlist=['x']).search_academic_rows('yapay zeka')
        self.assertEqual([row['url'] for row in rows],
                         ['https://doi.org/10.1/tr', 'https://arxiv.org/abs/1'])


class ModelUnavailableBranchTests(unittest.TestCase):
    """Canlı kusur (22 Kasım 2026 23:58): model HİÇ yokken istek "model kullanılamıyor" diyordu.

    O turda ne sağlayıcı hatası ne öneri reddi vardı; sebep kodu MODEL_UNAVAILABLE'dı ve
    akademik teslim yalnız provider_issue/rejected dallarına bağlanmıştı.
    """

    def test_handoff_delivers_the_list_in_the_model_unavailable_branch(self):
        source = Path(core_brain_adapter.__file__).read_text(encoding='utf-8')
        govde = source[source.index('def _handoff('):]
        son = govde.index('Doğal dil isteğini doğrulayacak model şu anda kullanılamıyor')
        # Model-yok dalında, genel ret mesajından ÖNCE akademik teslim denenmeli.
        self.assertIn('_academic_outage_answer(command, _runtime_owner(runtime))', govde[:son])
        self.assertIn('ACADEMIC_MODEL_FREE_DELIVERY', govde[:son])
