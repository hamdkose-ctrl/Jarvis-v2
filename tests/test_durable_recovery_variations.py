"""Variation regressions: real journal/file flows; external transport/model boundaries are mocked."""
from datetime import datetime,timezone,timedelta
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import copy
import unittest
from unittest.mock import patch,Mock
from modules import goal_executor as goals, goal_tools, publisher_news, news_recovery, brain_delegate, specialist_orchestrator
import test_goal_executor as fixture

REQUEST='Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır ve raporu dosyaya kaydet'

class RecoveryVariations(unittest.TestCase):
    def case(self):
        case=fixture.GoalTests();case.setUp();self.addCleanup(case.doCleanups);return case

    def test_public_question_inflections_and_private_scope(self):
        for q in ['Başka kaynakları paylaşır mısın?','Hangi kurumun duyurularını tarayayım?',
                  'Hangi ek kaynak incelensin?','Hangi üniversitenin haberlerini tarayayım?','Akademik yayınların adreslerini belirt.','Bir URL verir misin?']:
            with self.subTest(q=q):self.assertTrue(goals._self_resolvable_question(q,REQUEST))
        for q in ['Bu kaynağa giriş izni verir misin?','Hangi kuruma göndereyim?',
                  'Hangi kişinin hesabını kullanayım?','Hangi dosyayı okuyayım?','Özel kaynağının URL adresi nedir?','Hangi dosyalardaki kaynakları kullanayım?','API anahtarını ver.']:
            with self.subTest(q=q):self.assertFalse(goals._self_resolvable_question(q,REQUEST))
        self.assertFalse(goals._self_resolvable_question('Hangi ek kurum incelensin?',REQUEST+' https://example.org/story'))

    def test_catalog_requires_executed_exact_index_and_receipt(self):
        from modules import news_pipeline
        self.assertFalse(hasattr(publisher_news,'catalog_attempted'))
        self.assertFalse(hasattr(publisher_news,'catalog_keys'))
        self.assertFalse(news_pipeline.enough_evidence([{'news_article':{'url':'https://a.example/one'}},
                                                      {'news_article':{'url':'https://a.example/two'}}],REQUEST))
        self.assertTrue(news_pipeline.enough_evidence([{'news_article':{'url':'https://a.example/one'}},
                                                     {'news_article':{'url':'https://b.example/two'}}],REQUEST))

    def test_final_catalog_gate_is_explicit_and_not_latest_job_dependent(self):
        from modules import news_pipeline
        self.assertFalse(hasattr(publisher_news,'require_catalog'))
        with patch.object(goals,'latest',side_effect=AssertionError('No hidden journal lookup')):
            self.assertTrue(news_pipeline.enough_evidence([{'news_article':{'url':'https://a.example/story'}}],
                            'Sadece https://a.example/story haberini araştır'))

    def test_unchanged_recovery_releases_planner_and_does_not_claim_reads(self):
        job={'id':'a'*16,'owner':'alice','request':REQUEST,'state':'paused',
             'goals':[{'state':'pending'}],'steps':[{'id':'s1'}],
             'outputs':{'report':{'state':'done','file':'report.md'}},'partial_report':'report'}
        with patch.object(news_recovery,'deliver'),patch.object(goals,'_save'):
            self.assertFalse(goals._resume_news_recovery(SimpleNamespace(),job,1))
        self.assertIn('yeni kaynak okunmadı',job['blocker'])
        self.assertNotIn('yeniden taradı',job['blocker'])

    def test_recovery_failure_does_not_claim_success_and_permission_propagates(self):
        job={'id':'a'*16,'owner':'alice','request':REQUEST,'state':'paused','goals':[{'state':'pending'}],
             'steps':[{'id':'s1'}],'outputs':{},'partial_report':'s1'}
        with patch.object(news_recovery,'deliver',side_effect=ValueError('reader failed')),patch.object(goals,'_save'):
            self.assertFalse(goals._resume_news_recovery(SimpleNamespace(),job,1))
        for exc in [PermissionError('owner'),goals.requests_state.Cancelled('cancel')]:
            with self.subTest(exc=type(exc).__name__),patch.object(news_recovery,'deliver',side_effect=exc):
                with self.assertRaises(type(exc)):goals._resume_news_recovery(SimpleNamespace(),job,1)

    def canonical_case(self, *, first_bad=False, separate=False):
        from modules import news_pipeline
        from urllib.parse import urlsplit
        case=self.case()
        rows=[{'url':'https://www.aa.com.tr/tr/gundem','name':'AA'},
              {'url':'https://www.bbc.com/turkce','name':'BBC'}]
        indexes=[row['url'] for row in rows]
        fetched=[]
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        def fetch(url):
            fetched.append(url)
            if url in indexes:
                return {'url':url,'body':b'<h2><a href="/news/first">Turkiye yapay zeka ilk haber</a></h2><h2><a href="/news/second">Turkiye yapay zeka ikinci haber</a></h2>'}
            if first_bad and url=='https://www.aa.com.tr/news/first':
                raise ConnectionError('offline')
            text='Türkiye yapay zekâ araştırma projesinin yeni sonuçları ve kullanım alanları kamuoyuna açıklandı. Araştırmacılar teknik bulguları paylaştı.'
            return {'url':url,'body':f'<article><h1>Türkiye yapay zekâ projesi</h1><time itemprop="datePublished" datetime="{day}"></time><p>{text}</p></article>'.encode()}
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)
        case.responses(case.plan(*(['Haberleri araştır','Rapor dosyası oluştur'] if separate else ['Haberleri araştır ve rapor dosyası oluştur'])),
                       {'action':'ask','question':'Başka kaynakları paylaşır mısın?'})
        with patch.object(publisher_news,'sources_for',return_value=rows), \
             patch('modules.public_sources.fetch',side_effect=fetch), \
             patch('modules.research_providers.search_public',return_value=[]), \
             patch('modules.privacy.blocked',return_value=None):
            reply=goals.run(case.runtime,REQUEST)
        return case,goals.latest('alice'),fetched,reply

    def test_recovery_only_resume_scans_remaining_catalog_and_then_releases_planner(self):
        case,job,fetched,reply=self.canonical_case(separate=True)
        report=job['partial_report']
        saved=Path(job['outputs'][report]['file']).read_bytes()
        before=list(fetched)
        with patch('modules.public_sources.fetch',side_effect=AssertionError('saved evidence was fetched again')):
            self.assertFalse(goals._resume_news_recovery(case.runtime,job,len(job['steps'])))
        self.assertEqual(fetched,before)
        self.assertEqual(saved,Path(job['outputs'][report]['file']).read_bytes())
        self.assertTrue(goal_tools.verify(job['outputs'][report],'alice'))
        self.assertFalse(any(step['tool']=='data' for step in job['steps']))

    def test_resume_finishes_same_goal_after_catalog_without_replaying_files(self):
        case,before,fetched,reply=self.canonical_case()
        report=before['partial_report']
        path=Path(before['outputs'][report]['file'])
        saved=path.read_bytes()
        count=case.ask.call_count
        with patch('modules.public_sources.fetch',side_effect=AssertionError('completed news fetched again')):
            text=goals.run(case.runtime,'devam',resume=True)
        after=goals.latest('alice')
        self.assertEqual(after['id'],before['id'])
        self.assertEqual(after['state'],'done',text)
        self.assertEqual(path.read_bytes(),saved)
        self.assertEqual(case.ask.call_count,count)

    def test_bad_first_article_uses_second_link_and_writes_verified_file(self):
        case,job,fetched,reply=self.canonical_case(first_bad=True)
        output=job['outputs'][job['partial_report']]
        self.assertTrue(goal_tools.verify(output,'alice'))
        content=Path(output['file']).read_text(encoding='utf-8')
        self.assertIn('https://www.aa.com.tr/news/second',fetched)
        self.assertIn('https://www.aa.com.tr/news/second',content)
        self.assertNotIn('https://www.aa.com.tr/news/first>',content)
        self.assertEqual(case.ask.call_count,2)

    def test_final_completion_uses_verified_evidence_not_catalog_attempt_flags(self):
        case,job,fetched,reply=self.canonical_case()
        report=job['partial_report']
        job['news_catalog_attempted']=['forged']
        job['goals'][0].update(state='done',evidence=[report])
        self.assertTrue(goals._finish_completed(job))
        self.assertEqual(job['state'],'done')
        self.assertTrue(goal_tools.verify(job['outputs'][report],'alice'))

    def test_quota_file_request_uses_no_planner_model_and_verifies_delivery(self):
        with patch('modules.llm.quota_wait_seconds',return_value=42):
            case,job,fetched,reply=self.canonical_case()
        case.ask.assert_not_called()
        self.assertEqual(job['state'],'done',reply)
        report=job['outputs'][job['partial_report']]
        self.assertTrue(goal_tools.verify(report,'alice'))
        self.assertTrue(Path(report['file']).is_file())

    def test_durable_specialist_selection_uses_existing_execution_and_identity(self):
        case=self.case();case.responses(case.plan('Notu kaydet'),
              {**case.tool('action',{'action':'note_add','params':{'text':'Deneme'}}),'specialist':'operations'},case.done('s1'))
        bridge=SimpleNamespace(note_add=Mock(return_value={'id':1,'text':'Deneme'}))
        original=specialist_orchestrator.execute_step
        with patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(bridge)),patch.object(specialist_orchestrator,'execute_step',wraps=original) as execute:
            goals.run(case.runtime,'Bir not kaydet: Deneme')
        job=goals.latest('alice');self.assertEqual(job['state'],'done')
        self.assertEqual(job['steps'][0]['specialist']['id'],'operations')
        self.assertEqual(execute.call_args.args[1]['id'],job['id'])
        self.assertEqual(execute.call_args.args[3]['job_id'],job['id'])
        bridge.note_add.assert_called_once();self.assertEqual(case.ask.call_count,3)
        self.assertTrue(goals._context(job)['specialists'])
        for call in case.ask.call_args_list:
            self.assertNotIn('Uzman ekipleri',call.kwargs['system'])
            self.assertIn('specialists',call.args[0])

    def test_incompatible_specialist_cannot_execute_or_grant_permissions(self):
        self.case()
        with self.assertRaises(ValueError):brain_delegate.assign('alice','publish','mail gönder','development')
        with self.assertRaises(PermissionError):
            specialist_orchestrator.execute_step(SimpleNamespace(profile=SimpleNamespace(slug='bob')),{'owner':'alice'},{},{})

