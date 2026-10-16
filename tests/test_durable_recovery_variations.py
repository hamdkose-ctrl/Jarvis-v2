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
        rows=publisher_news.SOURCES
        job={'news_catalog_attempted':list(publisher_news.catalog_keys()),'steps':[],'outputs':{}}
        for i,row in enumerate(rows):
            job['steps'].append({'id':str(i),'tool':'data','started':True,'state':'queued','input':{'operation':'headlines','url':row['url']}})
            job['outputs'][str(i)]={'state':'done'}
        self.assertEqual(publisher_news.catalog_attempted(job),set())
        for step in job['steps']:step['state']='done'
        self.assertEqual(publisher_news.catalog_attempted(job),publisher_news.catalog_keys())
        job['steps'][0]['started']=False
        self.assertEqual(len(publisher_news.catalog_attempted(job)),3)
        job['steps'][0]['started']=True;job['steps'][0]['input']['url']=rows[0]['url']+'made-up'
        self.assertEqual(len(publisher_news.catalog_attempted(job)),3)

    def test_final_catalog_gate_is_explicit_and_not_latest_job_dependent(self):
        with patch.object(goals,'latest',side_effect=AssertionError('No hidden journal lookup')):
            self.assertTrue(publisher_news.broad_research(REQUEST))
        job={'request':REQUEST,'steps':[],'outputs':{}}
        with self.assertRaises(ValueError):publisher_news.require_catalog(job)
        publisher_news.require_catalog({**job,'request':REQUEST+' Yalnız TÜBİTAK.'})

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

    def real_transport(self,*,first_bad=False):
        indexes=[s['url'] for s in publisher_news.SOURCES];fetched=[]
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        def fetch(url):
            fetched.append(url)
            if url in indexes:
                n=indexes.index(url)
                return {'url':f'https://publisher{n}.example/','body':b'<a href="/news/first">Yapay zeka ilk haber</a><a href="/news/second">Yapay zeka ikinci haber</a>'}
            if first_bad and url=='https://publisher0.example/news/first':raise ConnectionError('offline')
            body=f'<article><h1>Yeni yapay zekâ projesi</h1><time itemprop="datePublished" datetime="{day}"></time><p>Üniversite yapay zekâ araştırma projesini bilimsel sonuçlarıyla kamuoyuna duyurdu. Araştırmacılar yeni projenin kapsamını açıkladı.</p></article>'
            return {'url':url,'body':body.encode()}
        return indexes,fetched,fetch

    def test_recovery_only_resume_scans_remaining_catalog_and_then_releases_planner(self):
        case=self.case();indexes,fetched,fetch=self.real_transport()
        case.responses(case.plan('Türkiye haberlerini araştır','Rapor dosyası oluştur'),{'action':'ask','question':'Eksik somut bilgi'})
        with patch('modules.public_sources.fetch',side_effect=fetch),patch('modules.privacy.blocked',return_value=None):
            goals.run(case.runtime,REQUEST)
            job=goals.latest('alice');old=job['partial_report'];old_bytes=Path(job['outputs'][old]['file']).read_bytes()
            self.assertEqual(len(publisher_news.catalog_attempted(job)),2)
            self.assertFalse(goals._resume_news_recovery(case.runtime,job,len(job['steps'])))
            self.assertEqual(publisher_news.catalog_attempted(job),publisher_news.catalog_keys())
            self.assertFalse(goals._resume_news_recovery(case.runtime,job,len(job['steps'])))
        self.assertEqual(case.ask.call_count,2)
        self.assertEqual(old_bytes,Path(job['outputs'][old]['file']).read_bytes())
        self.assertLessEqual(sum(bool(s.get('recovery')) for s in job['steps']),10)
        self.assertTrue(goal_tools.verify(job['outputs'][old],'alice'))

    def test_resume_finishes_same_goal_after_catalog_without_replaying_files(self):
        case=self.case();indexes,fetched,fetch=self.real_transport()
        case.responses(case.plan('Haberleri araştır ve rapor dosyası oluştur'),{'action':'ask','question':'Eksik somut bilgi'})
        with patch('modules.public_sources.fetch',side_effect=fetch),patch('modules.privacy.blocked',return_value=None):
            goals.run(case.runtime,REQUEST)
            before=goals.latest('alice');report=before['partial_report'];path=Path(before['outputs'][report]['file']);saved=path.read_bytes()
            case.responses(case.done(report))
            text=goals.run(case.runtime,'devam',resume=True)
        after=goals.latest('alice')
        self.assertEqual(after['id'],before['id']);self.assertEqual(after['state'],'done')
        self.assertEqual(publisher_news.catalog_attempted(after),publisher_news.catalog_keys())
        self.assertEqual(path.read_bytes(),saved);self.assertIn(str(path),text)
        self.assertEqual(case.ask.call_count,3)

    def test_bad_first_article_uses_second_link_and_writes_verified_file(self):
        case=self.case();indexes,fetched,fetch=self.real_transport(first_bad=True)
        case.responses(case.plan('Türkiye haberlerini araştır','Rapor dosyası oluştur'),
                       case.tool('data',{'operation':'headlines','url':indexes[0],'query':'yapay zeka dijital'}),
                       {'action':'ask','question':'Başka kaynakları paylaşır mısın?'})
        with patch('modules.public_sources.fetch',side_effect=fetch),patch('modules.privacy.blocked',return_value=None):
            goals.run(case.runtime,REQUEST)
        job=goals.latest('alice')
        self.assertIn('https://publisher0.example/news/second',fetched)
        self.assertEqual(publisher_news.catalog_attempted(job),publisher_news.catalog_keys())
        output=job['outputs'][job['partial_report']]
        self.assertTrue(goal_tools.verify(output,'alice'))
        self.assertIn('publisher0.example/news/second',Path(output['file']).read_text())
        self.assertIn('publisher0.example/news/first',Path(output['file']).read_text())
        self.assertEqual(case.ask.call_count,3)

    def test_final_completion_checks_actual_catalog_in_current_job(self):
        case=self.case();indexes,fetched,fetch=self.real_transport()
        case.responses(case.plan('Haberleri araştır ve rapor dosyası oluştur'),
                       case.tool('data',{'operation':'headlines','url':indexes[0],'query':'yapay zeka dijital'}),
                       {'action':'ask','question':'Başka kaynakları paylaşır mısın?'})
        with patch('modules.public_sources.fetch',side_effect=fetch),patch('modules.privacy.blocked',return_value=None):
            goals.run(case.runtime,REQUEST)
        job=goals.latest('alice');report=job['partial_report']
        index_step=next(s for s in job['steps'] if s['tool']=='data')
        same_index=[s for s in job['steps'] if s['tool']=='data' and s['input'].get('url')==index_step['input']['url']]
        for step in same_index:step['started']=False
        job['goals'][0].update(state='done',evidence=[report])
        self.assertFalse(goals._finish_completed(job));self.assertNotEqual(job['state'],'done')
        for step in same_index:step['started']=True
        job['goals'][0].update(state='done',evidence=[report])
        self.assertTrue(goals._finish_completed(job));self.assertEqual(job['state'],'done')
        self.assertTrue(goal_tools.verify(job['outputs'][report],'alice'))

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
