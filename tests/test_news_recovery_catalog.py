import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import news_recovery


class NewsRecoveryCatalogTests(unittest.TestCase):
    def test_broad_recovery_scans_registered_catalog_after_two_publishers(self):
        seeds=[f'https://publisher{i}.example/news' for i in range(4)]
        job={
            'id':'a'*16,'owner':'alice','state':'running',
            'request':'Türkiye yapay zekâ son 7 gündeki gelişmelerini araştır, rapor oluştur ve dosyaya kaydet',
            'goals':[{'state':'pending'}],
            'steps':[{'id':'s0','goal':0,'tool':'research','input':{'url':seeds[0]},'depends':[],
                      'signature':'normal-attempt','state':'failed'}],
            'outputs':{'s0':{'state':'failed','text':'Kaynak doğrulanamadı'}}
        }
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))

        def record(_runtime,current,step):
            step['state']='done'
            kind=step['tool'];data=step['input']
            if kind=='data':
                index=seeds.index(data['url'])
                output={'state':'done','structured':{'items':[{'title':'Yapay zekâ haberi','url':f'https://publisher{index}.example/article'}]}}
            elif kind=='research':
                url=data['url']
                output={'state':'done','news_article':{'url':url,'title':'AI','published':'2026-10-16','text':'Yapay zekâ kaynak metni'},
                        'source_quotes':['Yapay zekâ kaynak metni yeterli kanıt içerir.']}
            elif kind=='writer':
                output={'state':'done','file':'C:/tmp/report.md'}
            else:
                output={'state':'done'}
            current['outputs'][step['id']]=output

        with patch('modules.publisher_news.recovery_indexes',return_value=seeds), \
             patch('modules.publisher_news.broad_research',return_value=True), \
             patch('modules.publisher_news.publisher_key',side_effect=lambda url:url.split('/')[2]), \
             patch('modules.goal_executor._record',side_effect=record), \
             patch('modules.goal_executor._ensure'),patch('modules.goal_executor._save'), \
             patch('modules.goal_tools.verify'):
            news_recovery.deliver(runtime,job,max_new_steps=10)

        headlines=[s['input']['url'] for s in job['steps'] if s['tool']=='data' and s['input'].get('operation')=='headlines']
        self.assertEqual(headlines,seeds)
        self.assertLessEqual(sum(bool(s.get('recovery')) for s in job['steps']),10)
        self.assertIn('partial_report',job)


if __name__=='__main__':
    unittest.main()
