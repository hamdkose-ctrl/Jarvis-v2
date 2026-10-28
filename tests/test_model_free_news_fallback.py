import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from modules import model_free_news, news_recovery, specialist_orchestrator, task_results


class ModelFreeNewsFallbackTests(unittest.TestCase):
    def test_literal_news_selection_is_relevant_and_exact(self):
        article={
            'url':'https://news.example.org/a',
            'title':'İstanbul gündemi',
            'published':'2026-10-17',
            'text':'İstanbul gündemi İstanbul genelinde sabah saatlerinde yoğun yağış etkili oldu. Bazı vapur seferlerinde gecikmeler yaşandı. Ankara için ayrı bir açıklama yapıldı.'
        }
        quotes=model_free_news.quotes(article,'istanbul güncel haberler nelerdir')
        self.assertTrue(quotes)
        self.assertTrue(any('İstanbul' in q for q in quotes))
        normalized=' '.join(article['text'].split())
        self.assertTrue(all(' '.join(q.split()) in normalized for q in quotes))

    def test_breaking_news_phrase_does_not_create_a_false_topic(self):
        article = {'title': 'Kampüste etkinlik', 'text': 'Üniversite kampüsünde öğrenciler için kültür etkinliği düzenlendi ve katılımcılar çalışmalarını sundu.'}
        for request in ('son dakika haberleri', 'Son dakika haberleri!', 'son dakika haberler'):
            with self.subTest(request=request):
                self.assertEqual(model_free_news.terms(request), [])
                self.assertEqual(model_free_news.quotes(article, request), [article['text']])

    def test_breaking_news_keeps_the_requested_topic_and_rejects_unrelated_text(self):
        request = 'son dakika yapay zeka haberleri'
        self.assertEqual(model_free_news.terms(request), ['yapay', 'zeka'])
        with self.assertRaises(ValueError):
            model_free_news.quotes({'title': 'Kampüs', 'text': 'Üniversite kampüsünde öğrenciler için kültür etkinliği düzenlendi ve katılımcılar çalışmalarını sundu.'}, request)
        article = {'title': 'Teknoloji', 'text': 'Yapay zeka araştırmacıları yeni bir çalışma yayımladı ve sonuçları bilim dünyasıyla paylaştı.'}
        self.assertEqual(model_free_news.quotes(article, request), [article['text']])

    def test_minute_is_still_a_topic_outside_the_breaking_news_phrase(self):
        self.assertIn('dakika', model_free_news.terms('dakika başına üretim'))
        with self.assertRaises(ValueError):
            model_free_news.quotes({'title': 'Kampüs', 'text': 'Üniversite kampüsünde öğrenciler için kültür etkinliği düzenlendi ve katılımcılar çalışmalarını sundu.'}, 'dakika başına üretim')

    def test_durable_news_step_bypasses_goal_tool_llm_worker(self):
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='hamdi'))
        job={'owner':'hamdi','request':'istanbul güncel haberler nelerdir','outputs':{}}
        step={'tool':'research','input':{'url':'https://news.example.org/a','question':'son durum'},'depends':[]}
        expected={'state':'done','text':'kanıt'}
        with patch('modules.research_evidence.news_requested',return_value=True), \
             patch('modules.model_free_news.run',return_value=expected) as direct, \
             patch('modules.goal_tools.execute',side_effect=AssertionError('normal model worker çağrıldı')):
            result=specialist_orchestrator.execute_step(runtime,job,step,{'source_only':False})
        self.assertIs(result,expected)
        direct.assert_called_once_with('hamdi',step['input'],job['request'],source_only=False)

    def test_chat_recovery_seals_only_pipeline_verified_articles(self):
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='hamdi'))
        job={
            'id':'a'*16,'owner':'hamdi','request':'istanbul güncel haberler nelerdir','state':'running',
            'goals':[{'text':'İstanbul güncel haberlerini araştır','state':'pending','evidence':[]}],
            'steps':[],'outputs':{},
        }
        today=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        rows=[
            {'news_article':{'url':'https://news.example.org/a','title':'İstanbul yağış haberi',
                             'published':today,'text':'İstanbul genelinde doğrulanmış güncel gelişme açıklandı. Yetkililer araştırmanın ayrıntılarını kamuoyuyla paylaştı.'}},
            {'news_article':{'url':'https://other.example.net/b','title':'İstanbul ulaşım haberi',
                             'published':today,'text':'İstanbul ulaşımında doğrulanmış güncel değişiklik duyuruldu. Yetkililer yeni uygulamanın ayrıntılarını kamuoyuyla paylaştı.'}},
        ]
        def record(_runtime,current,step,approval=None):
            article=next(row['news_article'] for row in rows if row['news_article']['url']==step['input']['url'])
            text=article['text']
            current['outputs'][step['id']]={'state':'done','text':text,'source':article['url'],
                'source_chars':len(text),'source_quotes':[text],'source_only':True,'news_article':article}
            step['state']='done';step['started']=True
            return current['outputs'][step['id']]
        with patch('modules.news_pipeline.deliver_job',return_value={'verified':rows}) as pipeline, \
             patch('modules.goal_executor._ensure',return_value=None), \
             patch('modules.goal_executor._save',return_value=None), \
             patch('modules.goal_executor._record',side_effect=record), \
             patch('modules.goal_tools.verify'):
            news_recovery.deliver(runtime,job,max_new_steps=8)
        pipeline.assert_called_once()
        self.assertEqual(job['goals'][0]['state'],'done')
        self.assertEqual(len(job['goals'][0]['evidence']),2)
        recovery=[s for s in job['steps'] if s.get('recovery')]
        self.assertFalse(any(s['tool']=='data' for s in recovery))
        self.assertEqual(sum(s['tool']=='research' for s in recovery),2)
        self.assertTrue(all(s.get('source_only') is True for s in recovery))


if __name__=='__main__':
    unittest.main()

