"""A saved single publisher must recover before another long planner wait."""
from datetime import datetime,timezone,timedelta
import unittest
from unittest.mock import patch
import test_news_chat_writer as fixture
from modules import goal_executor as goals, news_recovery, publisher_news


class EarlyNewsRecoveryTests(unittest.TestCase):
    def prepared(self):
        scenario=fixture.NewsChatWriterTests();self.addCleanup(scenario.doCleanups)
        case,job,reply,work=scenario.run_case()
        job['request']='son dakika haberleri'
        job['steps']=job['steps'][:1];job['outputs']={'s1':job['outputs']['s1']}
        job['goals']=[{'text':'Haber kaynaklarını belirle','state':'done','evidence':['s1']},
                      {'text':'Haberleri araştır ve tarihlerini doğrula','state':'pending','evidence':[]},
                      {'text':'Haberleri özetleyerek sohbette sun','state':'pending','evidence':[]}]
        job['state']='paused';goals._save(job)
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        def fetch(url):
            if url.endswith('/new-story'):
                html='<article><h1>Güncel haber</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>Güncel gelişmeyle ilgili açıklama yayımlandı. Ekipler incelemelerinin sonuçlarını kamuoyuyla paylaşırken çalışmaların ayrıntılarını da duyurdu.</p></article>'
            else:html='<main><a href="/new-story">Güncel haber</a></main>'
            return {'url':url,'body':html.encode()}
        return case,job,fetch

    def test_first_invalid_completion_recovers_before_second_planner_wait(self):
        case,job,fetch=self.prepared()
        sequence=[{'action':'complete','goal':1,'evidence':['s1']},
                  goals._TurnBudget('120 saniyelik bütçe doldu')]
        with patch.object(goals,'_planner',side_effect=sequence) as planner, \
                patch('modules.public_sources.fetch',side_effect=fetch), \
                patch('modules.privacy.blocked',return_value=None):
            reply=goals.run(case.runtime,'devam',resume=True)
        after=goals.latest('alice')
        self.assertEqual(after['state'],'done',reply)
        self.assertEqual(planner.call_count,1)
        publishers={publisher_news.publisher_key(o['news_article']['url']) for o in after['outputs'].values() if o.get('news_article')}
        self.assertGreaterEqual(len(publishers),2)
        self.assertTrue(all(g['state']=='done' for g in after['goals']))

    def test_recovery_tries_unrepresented_publisher_first(self):
        case,job,fetch=self.prepared()
        with patch('modules.public_sources.fetch',side_effect=fetch) as reads, \
                patch('modules.privacy.blocked',return_value=None):
            news_recovery.deliver(case.runtime,job,max_new_steps=10)
        self.assertGreater(reads.call_count,0)
        self.assertNotEqual(publisher_news.publisher_key(reads.call_args_list[0].args[0]),
                            publisher_news.publisher_key(job['outputs']['s1']['news_article']['url']))
        self.assertLessEqual(sum(bool(s.get('recovery')) for s in job['steps']),10)
