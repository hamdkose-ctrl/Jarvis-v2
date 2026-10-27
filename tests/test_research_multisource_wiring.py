import json
from unittest.mock import Mock, patch
import re
import unittest

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
        return {'url': url, 'text': text, 'content_type': 'text/html'}

    def _fake_ask(self, prompt, system='', max_tokens=2000, **kwargs):
        if CLAIM_SENTINEL in system:
            body = prompt.split('):\n', 1)[-1]
            match = re.search(r'(?:yüzde|%)\s*(\d+(?:[.,]\d+)?)', body)
            value = match.group(1).replace(',', '.') if match else ''
            quote = ' '.join(body.split())[:80]
            return json.dumps({'value': value, 'quote': quote})
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
        third_text = 'Kurum raporu enerji tüketiminde düşüşün yüzde 40 olduğunu bağımsız olarak doğruluyor.'
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


def research_providers_compare(claims):
    from modules import research_providers
    return research_providers.compare_sources(claims)


if __name__ == '__main__':
    unittest.main()
