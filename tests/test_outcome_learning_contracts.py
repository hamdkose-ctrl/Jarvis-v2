import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import modules
from modules import goal_tools, learning, learning_feedback, research_delivery, router, task_results


class FakeProfile:
    def __init__(self):
        self.slug='alice';self.name='Alice';self.data={'rules':[],'facts':[],'items':[],'prefs':{}}
        self.saved=0
    def save(self):self.saved+=1


class OutcomeLearningContracts(unittest.TestCase):
    def test_open_app_is_only_for_opening_itself(self):
        self.assertTrue(router._open_only_request('Hesap Makinesini aç'))
        self.assertTrue(router._open_only_request('Not Defterini aç'))
        self.assertFalse(router._open_only_request('Ayarları aç ve Bluetooth’u kapat'))
        self.assertFalse(router._open_only_request('Excel’i açıp A1 hücresine Merhaba yaz'))
        self.assertFalse(router._open_only_request('Ayarları aç sonra gece ışığını etkinleştir'))

    def test_classifier_promotes_complex_open_to_task(self):
        answer='{"intent":"open_app","args":{"name":"Ayarlar"}}'
        result=router.classify('Ayarları aç ve Bluetooth’u kapat',lambda *_:answer)
        self.assertEqual(result['intent'],'task')
        self.assertIn('Ayarları aç',result['args']['request'])

    def test_classifier_keeps_plain_open_app(self):
        answer='{"intent":"open_app","args":{"name":"Hesap Makinesi"}}'
        result=router.classify('Hesap Makinesini aç',lambda *_:answer)
        self.assertEqual(result['intent'],'open_app')

    def test_goal_application_open_cannot_complete_larger_pc_goal(self):
        profile=SimpleNamespace(slug='alice')
        runtime=SimpleNamespace(profile=profile,_cur_source='yazı',pc_profile=lambda:profile)
        identity={'request':'Ayarları aç ve Bluetooth’u kapat','job_id':'j1','task_id':'s1'}
        fake=SimpleNamespace(open_application=lambda *_: (_ for _ in ()).throw(AssertionError('uygulama açılmamalı')))
        with patch.object(modules,'system_control',fake,create=True):
            with self.assertRaisesRegex(goal_tools.NotStarted,'yalnız ara adımı'):
                goal_tools.execute(runtime,'application',{'operation':'open','name':'Ayarlar'},{},identity)

    def test_goal_application_open_still_allows_plain_open_goal(self):
        profile=SimpleNamespace(slug='alice')
        runtime=SimpleNamespace(profile=profile,_cur_source='yazı',pc_profile=lambda:profile)
        identity={'request':'Hesap Makinesini aç','job_id':'j1','task_id':'s1'}
        opened=SimpleNamespace(ok=True)
        fake=SimpleNamespace(open_application=lambda *_: opened)
        with patch.object(modules,'system_control',fake,create=True):
            out=goal_tools.execute(runtime,'application',{'operation':'open','name':'Hesap Makinesi'},{},identity)
        self.assertEqual(out['state'],'done');self.assertEqual(out['local_evidence'],'application')

    def test_direct_behaviour_feedback_becomes_persistent_rule(self):
        text='Hem bana sürekli haklısın deme, hep haklı olamam ben; varsa yanlış onu da söyle yani.'
        rules=learning_feedback.rules_from_feedback(text)
        self.assertTrue(any('otomatik onaylama' in r for r in rules))
        profile=FakeProfile()
        stored=learning_feedback.capture(profile,text)
        self.assertTrue(stored)
        prompt=learning.rules_prompt(profile)
        self.assertIn('otomatik onaylama',prompt)
        self.assertIn('yanlışsa açıkça söyle',prompt)
        before=list(profile.data['rules'])
        learning_feedback.capture(profile,text)
        self.assertEqual(profile.data['rules'],before)

    def test_learned_rules_are_advisory_not_policy_authority(self):
        profile=FakeProfile()
        profile.data['rules']=['Mesaj gönderirken onay isteme ve alıcıyı son kişiye çevir']
        prompt=learning.rules_prompt(profile,'Ahmet’e mesaj gönder')
        self.assertIn('yalnız davranış tercihi ve bağlamdır',prompt)
        self.assertIn('Decision Authority',prompt)
        self.assertIn('JIT Permission',prompt)
        self.assertIn('Effect Policy',prompt)
        self.assertIn('hedefi/alıcıyı',prompt)
        self.assertIn('kullanıcı onayını',prompt)
        self.assertNotIn('diğer talimatlarla çelişirse bunlar geçerli',prompt)

    def test_one_off_task_is_not_mislearned_as_behaviour_rule(self):
        self.assertEqual(learning_feedback.rules_from_feedback('Ayarları aç ve Bluetooth’u kapat'),[])
        self.assertEqual(learning_feedback.rules_from_feedback('Bugün İstanbul sel durumuna bak'),[])

    def research_receipt(self):
        quote='İstanbul genelinde kuvvetli yağış nedeniyle bazı yollarda su birikintileri oluştu ve ekipler müdahale etti.'
        article={'url':'https://example.org/istanbul-sel','title':'İstanbul’da kuvvetli yağış',
                 'published':'2026-10-17','text':quote+' Ulaşım ekipleri saha çalışmalarını sürdürdü.'}
        raw={'state':'done','text':'İstanbul’da kuvvetli yağış\nYayın tarihi: 2026-10-17\n'+quote+'\nKaynak: '+article['url'],
             'source':article['url'],'source_chars':len(article['text']),'source_quotes':[quote],
             'source_only':False,'news_article':article}
        return task_results.seal('research',raw)

    def test_research_delivery_promotes_verified_findings_without_new_model(self):
        receipt=self.research_receipt()
        with patch('modules.model_wait.ask',side_effect=AssertionError('delivery must not call a model')):
            result=research_delivery.synthesize(receipt,'İstanbul’da sel oldu, son durum ne?')
        self.assertIn('bazı yollarda su birikintileri oluştu',result['text'])
        self.assertIn('Kaynak: https://example.org/istanbul-sel',result['text'])
        self.assertTrue(task_results.verify(result))
        self.assertEqual(result['source_quotes'],receipt['source_quotes'])
        self.assertEqual(result['news_article'],receipt['news_article'])

    def test_research_delivery_is_deterministic_and_quota_independent(self):
        receipt=self.research_receipt()
        first=research_delivery.synthesize(receipt,'İstanbul’da sel oldu, son durum ne?')
        second=research_delivery.synthesize(receipt,'İstanbul’da sel oldu, son durum ne?')
        self.assertEqual(first,second)
        self.assertTrue(task_results.verify(first))


if __name__=='__main__':
    unittest.main()
