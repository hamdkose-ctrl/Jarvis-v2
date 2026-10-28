"""Kaynak çatışması: kelime/zaman/scope farkı çelişki değildir; gerçek çelişkide sınırlı ek doğrulama.

Model/ağ/hesap çağrısı yok: search/extract/read_value enjekte edilir, doğrulama deterministiktir.
"""
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from modules import research_providers, task_workers


class ConflictModelTests(unittest.TestCase):
    def test_semantic_agreement_is_not_a_conflict(self):
        # A: aynı gerçeği farklı kelimelerle söyleyen iki kaynak conflict sayılmamalı.
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'şirket geliri', 'metric': 'gelir artışı',
             'claim': 'Şirket geliri yüzde 10 arttı.', 'value': 10, 'unit': '%'},
            {'url': 'https://b.test', 'subject': 'şirket geliri', 'metric': 'gelir artışı',
             'claim': 'Gelir geçen yıla göre yaklaşık %10 yükseldi.', 'value': 10, 'unit': '%'},
        ])
        self.assertEqual(comparison['status'], 'agreement')
        self.assertFalse(comparison['needs_review'])

    def test_semantic_agreement_from_free_text_numbers(self):
        # Aynı sayısal değer farklı cümledeyse de agreement olmalı (salt string eşitliği değil).
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'nüfus', 'claim': 'Nüfus 85 milyon kişi.'},
            {'url': 'https://b.test', 'subject': 'nüfus', 'claim': 'Ülke nüfusu yaklaşık 85 milyon olarak kaydedildi.'},
        ])
        self.assertEqual(comparison['status'], 'agreement')

    def test_numeric_conflict_is_detected(self):
        # B: aynı metrik/zaman/scope için farklı sayısal değer gerçek conflict adayıdır.
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %40.', 'value': 40, 'unit': '%'},
            {'url': 'https://b.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %45.', 'value': 45, 'unit': '%'},
        ])
        self.assertEqual(comparison['status'], 'conflict')
        self.assertTrue(comparison['needs_review'])

    def test_categorical_conflict_is_detected(self):
        # C: aynı olay için onaylandı/reddedildi gerçek conflict.
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'başvuru', 'claim': 'Başvuru onaylandı.'},
            {'url': 'https://b.test', 'subject': 'başvuru', 'claim': 'Başvuru reddedildi.'},
        ])
        self.assertEqual(comparison['status'], 'conflict')

    def test_time_difference_is_not_an_automatic_contradiction(self):
        # D: farklı as_of tarihleri eski/yeni ayrımıdır; otomatik contradiction değildir.
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'enflasyon', 'claim': '2020 için %12.', 'value': 12, 'unit': '%', 'as_of': '2020-01-01'},
            {'url': 'https://b.test', 'subject': 'enflasyon', 'claim': '2026 için %45.', 'value': 45, 'unit': '%', 'as_of': '2026-01-01'},
        ])
        self.assertNotEqual(comparison['status'], 'conflict')

    def test_scope_difference_is_not_a_conflict(self):
        # E: biri Türkiye diğeri global → aynı olgu değil, yanlış conflict üretme.
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'enflasyon', 'claim': 'Türkiye %45.', 'value': 45, 'unit': '%', 'scope': 'türkiye'},
            {'url': 'https://b.test', 'subject': 'enflasyon', 'claim': 'Global %7.', 'value': 7, 'unit': '%', 'scope': 'global'},
        ])
        self.assertNotEqual(comparison['status'], 'conflict')

    def test_third_source_resolves_conflict(self):
        # F: üçüncü kaynak bir tarafı destekliyorsa conflict çözülmüş işaretlenir ve kanıt görünür.
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %40.', 'value': 40, 'unit': '%'},
            {'url': 'https://b.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %45.', 'value': 45, 'unit': '%'},
        ])
        self.assertEqual(comparison['status'], 'conflict')

        def fake_search(query):
            return [{'provider': 'duckduckgo', 'title': 'Üçüncü kaynak', 'url': 'https://c.test',
                     'snippet': '', 'source_kind': 'web', 'verified': False}]

        def fake_extract(url):
            return {'url': url, 'text': 'Merkez bankası faiz oranını yüzde 45 olarak açıkladı.', 'content_type': 'text/plain'}

        resolved = research_providers.verify_conflict('faiz oranı', comparison, search=fake_search, extract=fake_extract)
        self.assertEqual(resolved['status'], 'resolved_conflict')
        self.assertEqual(resolved['supported']['value'], 45)
        self.assertIn('https://c.test', resolved['supported']['urls'])

    def test_third_source_that_cannot_resolve_stays_unresolved(self):
        # G: ek doğrulama kesinleştirmezse tek taraf seçilmez; belirsizlik açık kalır.
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %40.', 'value': 40, 'unit': '%'},
            {'url': 'https://b.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %45.', 'value': 45, 'unit': '%'},
        ])

        def fake_search(query):
            return [{'provider': 'duckduckgo', 'title': 'Belirsiz kaynak', 'url': 'https://c.test',
                     'snippet': '', 'source_kind': 'web', 'verified': False}]

        def fake_extract(url):
            return {'url': url, 'text': 'Piyasa faiz beklentisi yüzde 42 civarında.', 'content_type': 'text/plain'}

        unresolved = research_providers.verify_conflict('faiz oranı', comparison, search=fake_search, extract=fake_extract)
        self.assertEqual(unresolved['status'], 'unresolved_conflict')
        self.assertTrue(unresolved['needs_review'])
        self.assertIsNone(unresolved.get('supported'))

    def test_no_independent_source_is_unresolved_not_a_pick(self):
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %40.', 'value': 40, 'unit': '%'},
            {'url': 'https://b.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %45.', 'value': 45, 'unit': '%'},
        ])
        result = research_providers.verify_conflict('faiz oranı', comparison, search=lambda q: [], extract=lambda u: {'url': u, 'text': ''})
        self.assertEqual(result['status'], 'unresolved_conflict')

    def test_verify_skipped_when_there_is_no_conflict(self):
        comparison = research_providers.compare_sources([
            {'url': 'https://a.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %45.', 'value': 45, 'unit': '%'},
            {'url': 'https://b.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %45.', 'value': 45, 'unit': '%'},
        ])
        self.assertEqual(comparison['status'], 'agreement')
        calls = []
        result = research_providers.verify_conflict('faiz oranı', comparison,
                                                    search=lambda q: calls.append('search') or [],
                                                    extract=lambda u: calls.append('extract') or {'url': u, 'text': ''})
        self.assertEqual(result['status'], 'agreement')
        self.assertEqual(calls, [])  # agreement için ek doğrulama tetiklenmez (scenario A: gereksiz ağ yok)

    def test_comparison_is_deterministic_and_order_independent(self):
        # H: aynı evidence seti aynı sonucu verir; kaynak sırası sonucu değiştirmez.
        sources = [
            {'url': 'https://a.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %40.', 'value': 40, 'unit': '%'},
            {'url': 'https://b.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %45.', 'value': 45, 'unit': '%'},
            {'url': 'https://c.test', 'subject': 'faiz oranı', 'claim': 'Faiz oranı %40.', 'value': 40, 'unit': '%'},
        ]
        first = research_providers.compare_sources(sources)
        second = research_providers.compare_sources(sources)
        reversed_ = research_providers.compare_sources(list(reversed(sources)))
        self.assertEqual(first['status'], 'conflict')
        self.assertEqual(first, second)
        self.assertEqual(first['status'], reversed_['status'])
        self.assertEqual(first['comparisons'], reversed_['comparisons'])


class ResearchOutputWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        files = patch('modules.nxapi.FILES_DIR', Path(self.tmp.name) / 'files'); files.start(); self.addCleanup(files.stop)
        ask = patch('modules.model_wait.ask', return_value='Özet rapor gövdesi.'); ask.start(); self.addCleanup(ask.stop)

    def _task(self):
        return {'id': 'w1', 'agent': 'writer', 'input': {'instruction': 'Faiz oranını raporla', 'filename': 'faiz.md'},
                'execution': {'request': 'faiz oranı nedir'}}

    def _deps(self, first, second):
        first={'scope':'Türkiye','as_of':'2026',**first}
        second={'scope':'Türkiye','as_of':'2026',**second}
        return {'s1': {'state': 'done', 'source': 'https://a.test', 'source_claims': [first]},
                's2': {'state': 'done', 'source': 'https://b.test', 'source_claims': [second]}}

    def test_writer_report_surfaces_resolved_conflict(self):
        deps = self._deps({'subject': 'faiz oranı', 'value': 40, 'unit': '%'},
                          {'subject': 'faiz oranı', 'value': 45, 'unit': '%'})
        with patch('modules.research_providers.search_public', return_value=[{'url': 'https://c.test', 'title': 'C'}]) as search, \
             patch('modules.research_providers.extract_source', return_value={'url': 'https://c.test', 'text': 'Türkiye 2026 faiz oranı yüzde 45 açıklandı.', 'content_type': 'text/plain'}):
            output = task_workers.run('alice', self._task(), deps)
        self.assertEqual(output['source_conflict'], 'resolved_conflict')
        report = Path(output['file']).read_text(encoding='utf-8')
        self.assertIn('Kaynak çelişkisi doğrulandı', report)
        self.assertIn('45', report)
        self.assertIn('Özet rapor gövdesi.', report)

    def test_writer_report_surfaces_unresolved_conflict(self):
        deps = self._deps({'subject': 'faiz oranı', 'value': 40, 'unit': '%'},
                          {'subject': 'faiz oranı', 'value': 45, 'unit': '%'})
        with patch('modules.research_providers.search_public', return_value=[{'url': 'https://c.test', 'title': 'C'}]), \
             patch('modules.research_providers.extract_source', return_value={'url': 'https://c.test', 'text': 'Beklenti yüzde 42.', 'content_type': 'text/plain'}):
            output = task_workers.run('alice', self._task(), deps)
        self.assertEqual(output['source_conflict'], 'unresolved_conflict')
        report = Path(output['file']).read_text(encoding='utf-8')
        self.assertIn('Kaynak çelişkisi çözülmedi', report)

    def test_agreement_triggers_no_network_and_leaves_report_unchanged(self):
        deps = self._deps({'subject': 'faiz oranı', 'value': 45, 'unit': '%'},
                          {'subject': 'faiz oranı', 'value': 45, 'unit': '%'})
        with patch('modules.research_providers.search_public') as search, \
             patch('modules.research_providers.extract_source') as extract:
            output = task_workers.run('alice', self._task(), deps)
        self.assertNotIn('source_conflict', output)
        search.assert_not_called()
        extract.assert_not_called()
        report = Path(output['file']).read_text(encoding='utf-8')
        self.assertNotIn('çelişki', report)


if __name__ == '__main__':
    unittest.main()

