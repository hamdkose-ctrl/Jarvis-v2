"""Misrouted writer must deliver news to chat without another model/file attempt."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import unittest
from modules import goal_executor as goals,task_agents,task_results
import test_goal_executor as fixture


class NewsChatWriterTests(unittest.TestCase):
    def run_case(self, count=2, *, file=False, separate=False, stale=False):
        case=fixture.GoalTests();case.setUp();self.addCleanup(case.doCleanups)
        day=(datetime.now(timezone(timedelta(hours=3))).date()-timedelta(days=20 if stale else 0)).isoformat()
        urls=['https://one.example/story','https://two.example/story'][:count]
        plan=['Haberleri araştır','Kısa haber raporu'] if separate else ['Haberleri araştır ve kısa rapor ver']
        calls=[case.plan(*plan)]+[case.tool('research',{'url':url,'question':'Deprem haberleri'}) for url in urls]
        deps=['s'+str(i+1) for i in range(count)]
        if separate:calls.append(case.done(*deps))
        calls.append(case.tool('writer',{'instruction':'Kaynaklı haber raporu','filename':'rapor.md'},goal=1 if separate else 0,depends=deps))
        if file:
            calls+=[case.tool('verify',{},depends=['s3']),case.done('s3','s4')]
        case.responses(*calls)
        original=task_agents.worker
        def worker(owner,task,dependencies):
            if not file:raise AssertionError('Sohbet isteğinde writer çalışmamalı')
            return original(owner,task,dependencies)
        def fetch(url):
            if url not in urls:raise AssertionError('Beklenmeyen kaynak: '+url)
            text='Deprem sonrası ekiplerin incelemeleri hakkında doğrulanmış açıklama yayımlandı. Ayrıntılar yerel kurumların açıklamasıyla birlikte paylaşıldı.'
            html='<article><h1>Deprem incelemeleri</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>'+text+'</p></article>'
            return {'url':url,'body':html.encode()}
        request='Son dakika deprem haberlerini araştır ve kısa rapor ver'+(' ve raporu dosyaya kaydet' if file else '')
        with patch.object(task_agents,'worker',side_effect=worker),patch('modules.public_sources.fetch',side_effect=fetch) as work,patch('modules.privacy.blocked',return_value=None):
            reply=goals.run(case.runtime,request)
        return case,goals.latest('alice'),reply,work

    def test_two_publishers_deliver_without_writer_file_or_extra_model(self):
        case,job,reply,work=self.run_case()
        self.assertEqual(job['state'],'done',reply)
        self.assertEqual(case.ask.call_count,4);self.assertEqual(work.call_count,2)
        self.assertFalse(any(s['tool']=='writer' for s in job['steps']))
        self.assertIn('https://one.example/story',reply);self.assertIn('https://two.example/story',reply)
        self.assertFalse(list(case.root.rglob('*.md')))

    def test_separate_report_goal_uses_existing_research_evidence(self):
        case,job,reply,work=self.run_case(separate=True)
        self.assertEqual(job['state'],'done',reply)
        self.assertTrue(all(g['state']=='done' for g in job['goals']))
        self.assertEqual(case.ask.call_count,5);self.assertEqual(work.call_count,2)

    def test_single_publisher_is_partial_and_visible_without_retry(self):
        case,job,reply,work=self.run_case(count=1)
        self.assertNotEqual(job['state'],'done')
        self.assertIn('Kısmi:',reply);self.assertIn('https://one.example/story',reply)
        self.assertEqual(case.ask.call_count,3);self.assertEqual(work.call_count,1)

    def test_missing_news_does_not_loop_or_claim_completion(self):
        case,job,reply,work=self.run_case(count=0)
        self.assertNotEqual(job['state'],'done');self.assertEqual(case.ask.call_count,2)
        work.assert_not_called();self.assertNotIn('✓',reply)

    def test_generic_fileless_news_tries_publisher_recovery_before_planner(self):
        case=fixture.GoalTests();case.setUp();self.addCleanup(case.doCleanups)
        case.responses(case.plan('Haberler için normal plan'),RuntimeError('Planlayıcıya geri dön'))
        observed=[]
        def deliver(runtime,job,**kwargs):
            observed.append((case.ask.call_count,list(job['goals']),list(job['steps']),kwargs))
        with patch('modules.news_recovery.deliver',side_effect=deliver):
            goals.run(case.runtime,'Son dakika haberleri')
        self.assertEqual(case.ask.call_count,2)
        self.assertEqual(observed[0][0],0)
        self.assertEqual(observed[0][1][0]['text'],'Güncel haberleri tarihli kaynak kanıtlarıyla sohbetten teslim et')
        self.assertEqual(observed[0][2],[])
        self.assertEqual(observed[0][3]['max_new_steps'],24)
        self.assertEqual(observed[1][1][0]['text'],'Haberler için normal plan')

    def test_generic_fileless_news_recovery_error_falls_back_to_planner(self):
        case=fixture.GoalTests();case.setUp();self.addCleanup(case.doCleanups)
        case.responses(case.plan('Haberler için normal plan'),RuntimeError('Planlayıcıya geri dön'))
        with patch('modules.news_recovery.deliver',side_effect=RuntimeError('Dizin erişilemedi')):
            goals.run(case.runtime,'Son dakika haberleri')
        job=goals.latest('alice')
        self.assertEqual(case.ask.call_count,2)
        self.assertEqual(job['goals'][0]['text'],'Haberler için normal plan')
        self.assertTrue(any('Ön kaynak kurtarma tamamlanamadı' in item for item in job['feedback']))

    def test_explicit_file_request_still_writes_and_verifies_file(self):
        case,job,reply,work=self.run_case(file=True)
        self.assertEqual(job['state'],'done',reply)
        outputs=[o for o in job['outputs'].values() if o.get('file')]
        self.assertEqual(len(outputs),1);self.assertTrue(Path(outputs[0]['file']).is_file())
        self.assertTrue(task_results.verify(outputs[0],owner='alice'))

    def test_resume_old_writer_failure_delivers_existing_news_without_more_model_or_network(self):
        case,job,reply,work=self.run_case()
        job['state']='paused';job['goals'][0].update(state='pending',evidence=[])
        job['steps'].append({'id':'s3','goal':0,'tool':'writer','input':{'instruction':'Haber raporu','filename':'rapor.md'},
                             'depends':['s1','s2'],'signature':'old-writer','state':'failed','started':True})
        job['outputs']['s3']={'state':'failed','text':'Kullanıcı dosyaya kaydetmeyi istemedi.'}
        goals._save(job);case.ask.reset_mock();case.ask.side_effect=AssertionError('Ek planlayıcı çağrısı olmamalı')
        with patch('modules.public_sources.fetch',side_effect=AssertionError('Yeni ağ okuması olmamalı')):
            reply=goals.run(case.runtime,'devam',resume=True)
        self.assertEqual(goals.latest('alice')['state'],'done',reply)
        case.ask.assert_not_called()
