import unittest

from modules import router


class FreshResearchRoutingTests(unittest.TestCase):
    def test_istanbul_current_news_goes_to_task_without_model_router(self):
        def should_not_run(*_):
            raise AssertionError('Güncel haber isteği model routera bırakılmamalı')
        text='istanbul güncel haberler nelerdir'
        self.assertEqual(router.classify(text,should_not_run),{'intent':'task','args':{'request':text}})

    def test_latest_news_variants_go_to_task(self):
        for text in ('İstanbul son haberler neler?', 'Bugün İstanbul haberlerinde ne var?',
                     'Türkiye yapay zekâ son gelişmelerini anlat'):
            with self.subTest(text=text):
                self.assertEqual(router.classify(text,lambda *_: (_ for _ in ()).throw(AssertionError('router model called')))['intent'],'task')

    def test_static_explanation_stays_chat_capable(self):
        result=router.classify('Haber nedir?',lambda *_:'{"intent":"chat","args":{}}')
        self.assertEqual(result['intent'],'chat')

    def test_router_prompt_no_longer_sends_current_web_queries_to_chat(self):
        self.assertNotIn('genel güncel internet aramaları için intent="chat"',router.SYSTEM)
        self.assertIn('güncel haber/skor/piyasa',router.SYSTEM)


if __name__=='__main__':
    unittest.main()
