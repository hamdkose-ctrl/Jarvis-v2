"""Regression checks for common self-recovery policy. No live model, network or account calls."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules import goal_executor as goals


class GoalSelfRecoveryTests(unittest.TestCase):
    def test_public_source_selection_is_not_a_user_only_question(self):
        request='Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır ve raporu kaydet'
        self.assertTrue(goals._self_resolvable_question('Başka bir resmi haber veya akademik yayın kaynağı adı verin.',request))
        self.assertTrue(goals._self_resolvable_question('Eksik somut bilgi',request))
        self.assertFalse(goals._self_resolvable_question('Hangi kişiye göndermemi istiyorsun?',request))
        self.assertFalse(goals._self_resolvable_question('Bu dış gönderime izin veriyor musun?',request))

    def test_internal_planner_recovery_hints_do_not_leak_to_user(self):
        job={
            'request':'Türkiye yapay zekâ haberlerini araştır ve raporu dosyaya kaydet',
            'state':'paused','goals':[],
            'steps':[
                {'id':'s1','tool':'research','state':'failed','input':{},'depends':[]},
                {'id':'s2','tool':'research','state':'failed','input':{},'depends':[]},
                {'id':'s3','tool':'research','state':'failed','input':{},'depends':[]},
            ],
            'outputs':{
                's1':{'state':'failed','text':'Haber istenen tarih aralığının dışında; daha yeni kaynak seç.'},
                's2':{'state':'failed','text':'Bu adres haber dizini; data.headlines ile tekil haber bağlantısı seç.'},
                's3':{'state':'failed','text':'Bu haber adresi kayıtlı known_news_sources içinden gelmedi; URL yolu uydurma.'},
            },
            'feedback':['data operation=sources ve known_news_sources adresleriyle headlines kullan; URL yolu uydurma.'],
            'blocker':'Mevcut sonuçlar korundu; Jarvis başka doğrulanmış kaynakları kendi araçlarıyla denedi.',
        }
        text=goals.render(job)
        self.assertIn('Mevcut sonuçlar korundu',text)
        self.assertNotIn('data.headlines',text)
        self.assertNotIn('known_news_sources',text)
        self.assertNotIn('URL yolu uydurma',text)
        self.assertNotIn('daha yeni kaynak seç',text)

    def test_resume_with_partial_report_runs_modelsiz_recovery_before_planner(self):
        job={
            'id':'a'*16,'owner':'alice',
            'request':'Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır ve raporu dosyaya kaydet',
            'state':'paused','goals':[{'text':'Araştır ve raporla','state':'pending','evidence':[]}],
            'steps':[{'id':'s1','tool':'writer','state':'done','input':{},'depends':[]}],
            'outputs':{'s1':{'state':'done','file':'ilk.md'}},
            'partial_report':'s1',
        }
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        seen={}
        def recover(_runtime,current,**kwargs):
            seen.update(kwargs)
            current['steps'].append({'id':'s2','tool':'writer','state':'done','input':{},'depends':[]})
            current['outputs']['s2']={'state':'done','file':'ikinci.md'}
            current['partial_report']='s2'
        with patch('modules.research_evidence.news_requested',return_value=True), \
             patch('modules.news_recovery.deliver',side_effect=recover) as deliver, \
             patch.object(goals,'_save'):
            handled=goals._resume_news_recovery(runtime,job,started_steps=1)
        self.assertTrue(handled)
        deliver.assert_called_once()
        self.assertFalse(seen['existing_only'])
        self.assertEqual(job['partial_report'],'s2')
        self.assertIn('yeni doğrulanmış kaynaklarla',job['blocker'])

    def test_resume_without_partial_but_with_verified_article_only_delivers_existing_first(self):
        job={
            'id':'b'*16,'owner':'alice',
            'request':'Türkiye yapay zekâ haberlerini araştır ve raporu dosyaya kaydet',
            'state':'paused','goals':[{'text':'Araştır ve raporla','state':'pending','evidence':[]}],
            'steps':[{'id':'s1','tool':'research','state':'done','input':{},'depends':[]}],
            'outputs':{'s1':{'state':'done','news_article':{'url':'https://example.test/haber'}}},
        }
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        seen={}
        def recover(_runtime,current,**kwargs):
            seen.update(kwargs)
            current['steps'].append({'id':'s2','tool':'writer','state':'done','input':{},'depends':[]})
            current['outputs']['s2']={'state':'done','file':'kismi.md'}
            current['partial_report']='s2'
        with patch('modules.research_evidence.news_requested',return_value=True), \
             patch('modules.news_recovery.deliver',side_effect=recover), \
             patch.object(goals,'_save'):
            self.assertTrue(goals._resume_news_recovery(runtime,job,started_steps=1))
        self.assertTrue(seen['existing_only'])
        self.assertEqual(job['state'],'paused')


if __name__=='__main__':
    unittest.main()
