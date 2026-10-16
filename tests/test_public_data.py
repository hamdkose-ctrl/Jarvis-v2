"""Public-data boundary tests: untrusted search is not dated article evidence."""
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from modules import public_data, llm, goal_tools, goal_extensions, research_evidence


class PublicDataTests(unittest.TestCase):
    def setUp(self):
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        p=patch.object(public_data,'_SEARCH_NEXT',0);p.start();self.addCleanup(p.stop)

    def fetch(self,rows):
        body=json.dumps({'articles':rows}).encode()
        return Mock(side_effect=lambda url:{'url':url,'body':body}),body

    def test_search_filters_host_spoofs_unsafe_urls_and_deduplicates(self):
        rows=[{'title':'Gerçek haber','url':'https://news.tubitak.gov.tr/ai','seendate':'20261016T110000Z'},
              {'title':'Tekrar','url':'https://news.tubitak.gov.tr/ai'},
              {'title':'Sahte alan','url':'https://tubitak.gov.tr.evil.org/a'},
              {'title':'Son ek hilesi','url':'https://eviltubitak.gov.tr/a'},
              {'title':'Yerel','url':'https://127.0.0.1/a'},
              {'title':'Anahtar','url':'https://example.org/?api_key=secret'},
              {'title':'HTTP','url':'http://tubitak.gov.tr/a'},None]
        fetch,body=self.fetch(rows)
        result=public_data.news_search('alice','artificial intelligence',90,['tubitak.gov.tr'],20,fetcher=fetch)
        self.assertEqual([r['url'] for r in result['items']],['https://news.tubitak.gov.tr/ai'])
        self.assertEqual(result['items'][0]['published'],'');self.assertFalse(result['items'][0]['publication_verified'])
        self.assertFalse(result['coverage_complete']);self.assertEqual(result['sha256'],hashlib.sha256(body).hexdigest())
        query=parse_qs(urlsplit(fetch.call_args.args[0]).query)
        self.assertEqual(query['query'],['"artificial" "intelligence" (domain:tubitak.gov.tr)'])
        self.assertEqual(query['timespan'],['90d']);self.assertEqual(fetch.call_count,1)
        with self.assertRaises(ValueError):research_evidence.news_receipt({'state':'done',**result})

    def test_invalid_inputs_never_reach_network(self):
        bad=[{'query':'topic domain:evil.org'},{'query':'hello OR world'},{'query':'x\ny'},
             {'days':True},{'days':91},{'days':0},{'limit':False},{'limit':21},
             {'domains':[]},{'domains':['https://example.org']},{'domains':['127.0.0.1']},
             {'domains':['example.org OR other.org']},{'domains':['a..org']}]
        fetch=Mock()
        for values in bad:
            with self.subTest(values=values),self.assertRaises(ValueError):
                public_data.news_search('alice',**{'query':'artificial intelligence',**values},fetcher=fetch)
        fetch.assert_not_called()

    def test_owner_and_privacy_boundaries_are_preserved(self):
        fetch=Mock()
        with self.assertRaises(PermissionError):public_data.news_search('bob','science',fetcher=fetch)
        fetch.assert_not_called()
        with patch('modules.privacy.blocked',return_value='Gizlilik modu'):
            with self.assertRaises(PermissionError):public_data.news_search('alice','science')

    def test_cooldown_no_sleep_no_retry_and_429_backoff(self):
        fetch=Mock(side_effect=ValueError('Kaynak HTTP yanıtı başarılı değil: 429'))
        with patch.object(public_data.time,'monotonic',return_value=100):
            with self.assertRaisesRegex(ValueError,'429'):public_data.news_search('alice','science',fetcher=fetch)
        self.assertEqual(public_data._SEARCH_NEXT,160)
        with patch.object(public_data.time,'monotonic',return_value=159):
            with self.assertRaisesRegex(ValueError,'beklemede'):public_data.news_search('alice','science',fetcher=fetch)
        self.assertEqual(fetch.call_count,1)

    def test_empty_result_is_distinct_from_malformed_or_service_error(self):
        fetch,_=self.fetch([])
        result=public_data.news_search('alice','science',fetcher=fetch)
        self.assertEqual(result['items'],[])
        for body in [b'<html>error</html>',b'{"error":"quota"}',b'{"articles":null}']:
            with self.subTest(body=body),patch.object(public_data,'_SEARCH_NEXT',0):
                with self.assertRaises(ValueError):
                    public_data.news_search('alice','science',fetcher=lambda url:{'url':url,'body':body})

    def test_catalog_and_real_goal_adapter_need_no_model_account_or_binding(self):
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        identity={'owner':'alice','job_id':'job','task_id':'s1','request':'Haber kaynaklarını listele'}
        with patch.object(llm,'ask',side_effect=AssertionError('No model')):
            out=goal_tools.execute(runtime,'data',{'operation':'sources'},{},identity)
        self.assertTrue(goal_tools.verify(out,'alice'))
        self.assertEqual(len(out['structured']['sources']),3)
        self.assertFalse(out['structured']['live_connection_tested'])
        row=public_data.catalog('alice');row['sources'][0]['operation']='changed'
        self.assertEqual(public_data.catalog('alice')['sources'][0]['operation'],'news_search')
        data={'operation':'news_search','query':'science','days':30,'domains':['edu.tr'],'limit':2}
        self.assertEqual(goal_extensions.validate('data',data),data)
        fetch,_=self.fetch([{'title':'Araştırma','url':'https://example.edu.tr/article'}])
        with patch.object(public_data.public_sources,'fetch',fetch),patch.object(llm,'ask',side_effect=AssertionError('No model')):
            out=goal_tools.execute(runtime,'data',data,{},identity)
        self.assertTrue(goal_tools.verify(out,'alice'));self.assertIn('yayın tarihi değildir',out['text'])
        self.assertFalse(out.get('news_article'));self.assertFalse(out.get('file'))


if __name__=='__main__':unittest.main()
