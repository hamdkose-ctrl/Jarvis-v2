"""Three bad planner completions stop models, then use bounded existing news readers."""
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from test_stale_goal_and_quota import _Base
from modules import goal_executor as goals, publisher_news


class InvalidNewsDecisionRecoveryTests(_Base):
    def run_news(self,available):
        request='son dakika haberleri'
        indexes=publisher_news.recovery_indexes(request,[])
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        def fetch(url):
            if not available:raise OSError('Offline test source')
            if url in indexes:
                body='<main><a href="/gercek-haber-1">Güncel gelişme haberi</a></main>'
            else:
                body='<article><h1>Güncel gelişme haberi</h1><time itemprop="datePublished" datetime="'+day+'"></time><p>Güncel gelişmeyle ilgili açıklama yayımlandı. Ekipler incelemelerinin sonuçlarını kamuoyuyla paylaşırken çalışmaların ayrıntılarını da duyurdu.</p></article>'
            return {'url':url,'body':body.encode()}
        sequence=[{'action':'plan','goals':['Son dakika haberlerini araştır']}] + [
            {'action':'complete','goal':0,'evidence':['not-a-real-step']}] * 3
        with patch.object(goals,'_planner',side_effect=sequence) as planner, \
                patch('modules.public_sources.fetch',side_effect=fetch) as reads, \
                patch('modules.privacy.blocked',return_value=None):
            reply=goals.run(self.runtime,request)
        return goals.latest('alice'),reply,planner,reads,indexes

    def test_reads_real_receipts_and_delivers_without_fourth_model_retry(self):
        job,reply,planner,reads,indexes=self.run_news(True)
        self.assertEqual(job['state'],'done',reply)
        self.assertEqual(planner.call_count,4)
        self.assertEqual(len(job['decision_diagnostics']),3)
        self.assertTrue(any(s.get('recovery') for s in job['steps']))
        self.assertFalse(any(s['tool']=='writer' for s in job['steps']))
        articles=[o['news_article'] for o in job['outputs'].values() if o.get('news_article')]
        self.assertGreaterEqual(len({publisher_news.publisher_key(a['url']) for a in articles}),2)
        self.assertGreaterEqual(len(set(indexes)&{c.args[0] for c in reads.call_args_list}),2)
        self.assertLessEqual(len(job['steps']),10)

    def test_unavailable_sources_keep_paused_and_original_three_decision_limit(self):
        job,reply,planner,reads,indexes=self.run_news(False)
        self.assertEqual(job['state'],'paused')
        self.assertEqual(planner.call_count,4)
        self.assertIn('3 geçersiz karar',reply)
        self.assertGreater(reads.call_count,0)
        self.assertLessEqual(len(job['steps']),10)
        self.assertFalse(any(o.get('news_article') for o in job['outputs'].values()))
