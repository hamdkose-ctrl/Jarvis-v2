import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import research_evidence, task_workers

CLAIM_SENTINEL = 'İDDİA'  # matches the structured-claim system prompt used by the research worker


class ResearchMultiSourceClaimWiringTests(unittest.TestCase):
    """Real worker → real dependency/output → real cross_source_review, with only the model/network
    boundaries faked. compare_sources / verify_conflict are exercised for real, never mocked away."""

    def _task(self, query='enerji verimliliği araştırması'):
        return {
            'id': 'research-multi-1',
            'agent': 'research',
            'input': {'query': query, 'question': 'Enerji tüketimi yüzde kaç azaldı?'},
            'execution': {'request': 'Enerji araştırması'},
        }

    def _candidate(self, url):
        return {'provider': 'duckduckgo', 'title': 'Kaynak ' + url, 'url': url,
                'snippet': '', 'source_kind': 'web', 'verified': False}

    def _source(self, url, text):
        context='Ölçüm kapsamı: aynı ölçüm bölgesi. Referans dönemi: 2026. '
        return {'url': url, 'text': context+text, 'content_type': 'text/html'}

    def _fake_ask(self, prompt, system='', max_tokens=2000, **kwargs):
        if CLAIM_SENTINEL in system:
            body = prompt.split('):\n', 1)[-1]
            match = re.search(r'(?:yüzde|%)\s*(\d+(?:[.,]\d+)?)', body)
            value = match.group(1).replace(',', '.') if match else ''
            quote = ' '.join(body.split())[:800]
            return json.dumps({'value': value, 'quote': quote,
                               'scope':'aynı ölçüm bölgesi','as_of':'2026'})
        body = prompt.split('KAYNAK', 1)[-1]
        match = re.search(r'\):\n(.*)', body, re.S)
        text = match.group(1) if match else body
        quote = ' '.join(text.split())[:80]
        return json.dumps({'supported': True, 'answer': 'Özet cevap.', 'quotes': [quote]})

    def _run(self, candidate_urls, text_by_url, *, failing=()):
        candidates = [self._candidate(u) for u in candidate_urls]

        def extract(url, **kwargs):
            if url in failing:
                raise ConnectionError('kaynak erişilemedi: ' + url)
            return self._source(url, text_by_url[url])

        with patch('modules.privacy.blocked', return_value=None), \
             patch('modules.research_providers.search_public', return_value=candidates), \
             patch('modules.research_providers.extract_source', side_effect=extract), \
             patch('modules.model_wait.ask', side_effect=self._fake_ask):
            return task_workers.run('alice', self._task(), {})

    def test_worker_emits_multiple_independent_source_claims(self):
        first, second = 'https://a.test/x', 'https://b.test/y'
        output = self._run([first, second], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve bu sonuç bağımsız tekrarlanmıştır.',
            second: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
        })
        self.assertEqual(output['state'], 'done')
        self.assertEqual(output['source'], first)
        self.assertIn('Özet cevap.', output['text'])
        claims = output.get('source_claims')
        self.assertIsInstance(claims, list)
        self.assertGreaterEqual(len(claims), 2)
        urls = {claim['url'] for claim in claims}
        self.assertEqual(urls, {first, second})
        values = {claim['value'] for claim in claims}
        self.assertEqual(values, {'40', '45'})

    def test_first_unreadable_candidate_is_skipped_once(self):
        first,second='https://a.test/first','https://b.test/second'
        text='Enerji tüketimi yüzde 40 azaldı ve bağımsız araştırmanın ayrıntıları kamuoyuyla paylaşıldı.'
        calls=[]
        def extract(url):
            calls.append(url)
            if url==first:raise OSError('offline')
            return self._source(url,text)
        with patch('modules.privacy.blocked',return_value=None), \
             patch('modules.research_providers.search_public',return_value=[self._candidate(first),self._candidate(second)]), \
             patch('modules.research_providers.extract_source',side_effect=extract), \
             patch('modules.model_wait.ask',side_effect=self._fake_ask):
            result=task_workers.run('alice',self._task(),{})
        self.assertEqual(result['source'],second)
        self.assertEqual(calls,[first,second])

    def test_claim_quota_failure_stops_following_model_calls(self):
        urls=['https://a.test/x','https://b.test/x','https://c.test/x']
        source=self._source(urls[0],'Enerji tüketimi yüzde 40 azaldı ve araştırmanın ayrıntıları kamuoyuyla paylaşıldı.')
        summary=json.dumps({'supported':True,'answer':'Kaynak cevabı.','quotes':[source['text'][:80]]})
        with patch('modules.privacy.blocked',return_value=None), \
             patch('modules.research_providers.search_public',return_value=[self._candidate(url) for url in urls]), \
             patch('modules.research_providers.extract_source',side_effect=lambda url:dict(source,url=url)) as extract, \
             patch('modules.model_wait.ask',side_effect=[summary,RuntimeError('429 kota')]) as ask:
            result=task_workers.run('alice',self._task(),{})
        self.assertEqual(result['state'],'done')
        self.assertEqual(ask.call_count,2)
        self.assertEqual(extract.call_count,1)

    def test_unknown_measurement_context_does_not_trigger_false_agreement_or_extra_search(self):
        from modules import research_evidence
        output={'state':'done','source_claims':[
            {'subject':'enerji','scope':'','as_of':'','value':'40','url':'https://a.test/x','evidence':'Kaynakta yüzde 40 açıklandı.'},
            {'subject':'enerji','scope':'','as_of':'','value':'45','url':'https://b.test/x','evidence':'Kaynakta yüzde 45 açıklandı.'}]}
        search=Mock(side_effect=AssertionError('unknown context consumed discovery budget'))
        verdict=research_evidence.cross_source_review({'r':output},search=search,extract=Mock())
        self.assertEqual(verdict['status'],'insufficient_context')
        self.assertIn('referans dönemi',verdict['text'])
        search.assert_not_called()

    def test_two_agreeing_sources_flow_to_conflict_review_as_no_conflict(self):
        first, second = 'https://a.test/x', 'https://b.test/y'
        output = self._run([first, second], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 10 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Farklı bir ekip tüketimin yaklaşık yüzde 10 gerilediğini ayrı bir çalışmada bulmuştur.',
        })
        claims = output.get('source_claims')
        self.assertEqual({claim['value'] for claim in claims}, {'10'})
        # compare_sources groups these under the same subject/scope/as_of -> agreement, never raw-prose conflict.
        comparison = research_providers_compare(claims)
        self.assertEqual(comparison['status'], 'agreement')
        review_search, review_extract = Mock(), Mock()
        review = research_evidence.cross_source_review({'r1': output},
            search=review_search, extract=review_extract)
        self.assertIsNone(review)
        review_search.assert_not_called()
        review_extract.assert_not_called()

    def test_real_conflict_reaches_review_and_resolves_with_bounded_third_source(self):
        first, second = 'https://a.test/x', 'https://b.test/y'
        output = self._run([first, second], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
        })
        third_text = 'aynı ölçüm bölgesi, 2026. Kurum raporu enerji tüketiminde düşüşün yüzde 40 olduğunu bağımsız olarak doğruluyor.'
        review = research_evidence.cross_source_review({'r1': output},
            search=lambda q: [self._candidate('https://c.test/z')],
            extract=lambda url, **kw: self._source(url, third_text))
        self.assertEqual(review['status'], 'resolved_conflict')
        self.assertIn('Kaynak çelişkisi doğrulandı', review['text'])
        self.assertIn('40', review['text'])

    def test_unresolved_conflict_surfaces_uncertainty_without_picking_a_side(self):
        first, second = 'https://a.test/x', 'https://b.test/y'
        output = self._run([first, second], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
        })
        ambiguous_text = 'Bağımsız kaynak tüketimin yüzde 42 azaldığını belirtiyor ancak ölçüm tartışmalı.'
        review = research_evidence.cross_source_review({'r1': output},
            search=lambda q: [self._candidate('https://c.test/z')],
            extract=lambda url, **kw: self._source(url, ambiguous_text))
        self.assertEqual(review['status'], 'unresolved_conflict')
        self.assertIn('Kaynak çelişkisi çözülmedi', review['text'])
        self.assertIn('belirsizdir', review['text'])

    def test_single_candidate_keeps_safe_single_source_behaviour(self):
        first = 'https://a.test/x'
        output = self._run([first], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
        })
        self.assertEqual(output['state'], 'done')
        self.assertFalse(output.get('source_claims'))
        review = research_evidence.cross_source_review({'r1': output}, search=Mock(), extract=Mock())
        self.assertIsNone(review)

    def test_one_inaccessible_source_still_produces_claims_from_the_rest(self):
        first, broken, third = 'https://a.test/x', 'https://b.test/y', 'https://c.test/z'
        output = self._run([first, broken, third], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            third: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
        }, failing={broken})
        self.assertEqual(output['state'], 'done')
        urls = {claim['url'] for claim in output['source_claims']}
        self.assertEqual(urls, {first, third})

    def test_differently_worded_same_value_sources_stay_conflict_free(self):
        first, second, third = 'https://a.test/x', 'https://b.test/y', 'https://c.test/z'
        output = self._run([first, second, third], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 10 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Ayrı bir çalışma tüketimin %10 oranında gerilediğini raporlamış ve ölçüm bağımsız olarak yinelenmiştir.',
            third: 'Bağımsız değerlendirmede yaklaşık yüzde 10 düşüş ölçüldüğü belirtildi; ekip bulguyu ayrı bir tabloda yayımladı.',
        })
        self.assertEqual({claim['value'] for claim in output['source_claims']}, {'10'})
        self.assertEqual(len(output['source_claims']), 3)
        review_search, review_extract = Mock(), Mock()
        self.assertIsNone(research_evidence.cross_source_review({'r1': output},
            search=review_search, extract=review_extract))
        review_search.assert_not_called()
        review_extract.assert_not_called()

    def test_research_worker_claims_reach_writer_report_end_to_end(self):
        """Production path: the research worker's own output is handed to the writer as a dependency."""
        first, second = 'https://a.test/x', 'https://b.test/y'
        output = self._run([first, second], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
        })
        self.assertGreaterEqual(len(output['source_claims']), 2)
        writer = {
            'id': 'writer-multi-1',
            'agent': 'writer',
            'input': {'instruction': 'Enerji araştırmasını raporla', 'filename': 'enerji.md'},
            'execution': {'request': 'Enerji tüketimi araştırması'},
        }
        third = {'url': 'https://d.test/w', 'text': 'aynı ölçüm bölgesi, 2026. Kurum raporu düşüşün yüzde 40 olduğunu bağımsız doğruluyor.',
                 'content_type': 'text/plain'}
        with tempfile.TemporaryDirectory() as tmp, \
             patch('modules.nxapi.FILES_DIR', Path(tmp) / 'files'), \
             patch('modules.model_wait.ask', return_value='Enerji raporu gövdesi.'), \
             patch('modules.research_providers.search_public', return_value=[self._candidate(third['url'])]) as extra_search, \
             patch('modules.research_providers.extract_source', return_value=third) as extra_extract:
            report = task_workers.run('alice', writer, {'r1': output})
            text = Path(report['file']).read_text(encoding='utf-8')
        self.assertEqual(report['state'], 'done')
        self.assertEqual(report['source_conflict'], 'resolved_conflict')
        self.assertIn('Enerji raporu gövdesi.', text)
        self.assertIn('Kaynak çelişkisi doğrulandı', text)
        self.assertIn('40', text)
        self.assertEqual(extra_search.call_count, 1)
        self.assertEqual(extra_extract.call_count, 1)

    def test_unresolved_conflict_reaches_writer_report_as_uncertainty(self):
        first, second = 'https://a.test/x', 'https://b.test/y'
        output = self._run([first, second], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
        })
        writer = {
            'id': 'writer-multi-2',
            'agent': 'writer',
            'input': {'instruction': 'Enerji araştırmasını raporla', 'filename': 'enerji.md'},
            'execution': {'request': 'Enerji tüketimi araştırması'},
        }
        ambiguous = {'url': 'https://d.test/w', 'text': 'Bağımsız kaynak düşüşün yüzde 42 civarında olduğunu belirtiyor.',
                     'content_type': 'text/plain'}
        with tempfile.TemporaryDirectory() as tmp, \
             patch('modules.nxapi.FILES_DIR', Path(tmp) / 'files'), \
             patch('modules.model_wait.ask', return_value='Enerji raporu gövdesi.'), \
             patch('modules.research_providers.search_public', return_value=[self._candidate(ambiguous['url'])]), \
             patch('modules.research_providers.extract_source', return_value=ambiguous):
            report = task_workers.run('alice', writer, {'r1': output})
            text = Path(report['file']).read_text(encoding='utf-8')
        self.assertEqual(report['source_conflict'], 'unresolved_conflict')
        self.assertIn('Kaynak çelişkisi çözülmedi', text)
        self.assertIn('belirsizdir', text)

    def test_independent_candidate_selection_is_host_distinct_and_bounded(self):
        from modules import research_providers
        rows = [self._candidate(u) for u in (
            'https://a.test/1', 'https://a.test/2', 'https://b.test/1',
            'https://c.test/1', 'https://d.test/1', 'https://e.test/1')]
        chosen = research_providers.independent_candidates(rows)
        self.assertEqual([row['url'] for row in chosen],
                         ['https://a.test/1', 'https://b.test/1', 'https://c.test/1'])
        self.assertEqual(chosen, research_providers.independent_candidates(rows))

    def test_source_claim_is_structured_not_raw_prose(self):
        first, second = 'https://a.test/x', 'https://b.test/y'
        output = self._run([first, second], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
        })
        for claim in output['source_claims']:
            self.assertEqual(set(claim), {'subject', 'scope', 'as_of', 'value', 'url', 'evidence'})
            self.assertTrue(claim['subject'] and claim['value'] and claim['url'] and claim['evidence'])
            self.assertLess(len(claim['value']), len(claim['evidence']))

    def test_invented_value_is_rejected_by_claim_parser(self):
        source = 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.'
        self.assertIsNone(research_evidence.parse_value_quote(
            json.dumps({'value': '99', 'quote': 'Tüketim yüzde 99 azaldı ve bu bağımsız kaynakça doğrulandı'}), source))
        self.assertIsNone(research_evidence.parse_value_quote('metin değil', source))
        parsed = research_evidence.parse_value_quote(
            json.dumps({'value': '40', 'quote': 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır'}), source)
        self.assertEqual(parsed['value'], '40')

    def test_three_distinct_values_never_pick_a_side(self):
        first, second, third = 'https://a.test/x', 'https://b.test/y', 'https://c.test/z'
        output = self._run([first, second, third], {
            first: 'Yapılan ölçümde enerji tüketimi yüzde 40 oranında azalmıştır ve sonuç tekrarlanmıştır.',
            second: 'Başka bir ekip aynı bölgede yaptığı bağımsız ölçümde tüketimin yüzde 45 düştüğünü raporlamıştır.',
            third: 'Üçüncü çalışma tüketim azalmasını yüzde 42 olarak ölçtüğünü ayrı bir tabloda yayımlamıştır.',
        })
        self.assertEqual({claim['value'] for claim in output['source_claims']}, {'40', '45', '42'})
        review = research_evidence.cross_source_review({'r1': output},
            search=lambda q: [self._candidate('https://d.test/w')],
            extract=lambda url, **kw: self._source(url, 'Kurum düşüşün yüzde 40 olduğunu bağımsız doğruluyor.'))
        self.assertEqual(review['status'], 'unresolved_conflict')
        self.assertIsNone(review['verdict'].get('supported'))
        self.assertIn('belirsizdir', review['text'])


def research_providers_compare(claims):
    from modules import research_providers
    return research_providers.compare_sources(claims)


if __name__ == '__main__':
    unittest.main()

