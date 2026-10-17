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

    def test_chat_recovery_uses_failed_directory_as_headlines_and_finishes_with_two_articles(self):
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='hamdi'))
        job={
            'id':'a'*16,'owner':'hamdi','request':'istanbul güncel haberler nelerdir','state':'running',
            'goals':[{'text':'İstanbul güncel haberlerini araştır','state':'pending','evidence':[]}],
            'steps':[{'id':'s1','goal':0,'tool':'research','input':{'url':'https://news.example.org/haberler','question':'güncel'},
                      'depends':[],'signature':'old','state':'failed','started':True}],
            'outputs':{'s1':{'state':'failed','text':'Tekil haber gövdesi doğrulanamadı.'}},
        }
        today=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        def sealed(url,text):
            article={'url':url,'title':'İstanbul haberi','published':today,'text':text}
            return task_results.seal('research',{'state':'done','text':text,'source':url,'source_chars':len(text),
                'source_quotes':[text],'source_only':True,'news_article':article})
        def record(_runtime,current,step,approval=None):
            if step['tool']=='data':
                current['outputs'][step['id']]={'state':'done','text':'başlıklar','owner':'hamdi','local_evidence':'data',
                    'structured':{'items':[{'url':'https://news.example.org/a','title':'İstanbul yağış haberi','summary':''},
                                           {'url':'https://news.example.org/b','title':'İstanbul ulaşım haberi','summary':''}]}}
            else:
                url=step['input']['url']
                text=('İstanbul genelinde güncel gelişme hakkında doğrulanmış açıklama yayımlandı ve ilgili kurum ayrıntıların gün içinde yeniden paylaşılacağını bildirdi.' if url.endswith('/a') else
                      'İstanbul ulaşımında güncel değişiklikler resmi kaynak tarafından duyuruldu ve yolcuların sefer saatlerini çıkmadan önce kontrol etmesi istendi.')
                current['outputs'][step['id']]=sealed(url,text)
            step['state']='done';step['started']=True
            return current['outputs'][step['id']]
        with patch('modules.goal_executor._ensure',return_value=None), \
             patch('modules.goal_executor._save',return_value=None), \
             patch('modules.goal_executor._record',side_effect=record):
            news_recovery.deliver(runtime,job,max_new_steps=8)
        self.assertEqual(job['goals'][0]['state'],'done')
        self.assertEqual(len(job['goals'][0]['evidence']),2)
        recovery=[s for s in job['steps'] if s.get('recovery')]
        self.assertTrue(any(s['tool']=='data' for s in recovery))
        self.assertEqual(sum(s['tool']=='research' for s in recovery),2)
        self.assertFalse(any(s['tool']=='writer' for s in recovery))
        self.assertTrue(all(s.get('source_only') is True for s in recovery if s['tool']=='research'))


if __name__=='__main__':
    unittest.main()
