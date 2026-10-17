import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import goal_tools, learning, learning_feedback, router


class FakeProfile:
    def __init__(self):
        self.slug='alice';self.name='Alice';self.data={'rules':[],'facts':[],'items':[],'prefs':{}}
        self.saved=0
    def save(self):self.saved+=1


class OutcomeLearningContracts(unittest.TestCase):
    def test_open_app_is_only_for_opening_itself(self):
        self.assertTrue(router._open_only_request('Hesap Makinesini aç'))
        self.assertTrue(router._open_only_request('Not Defteri uygulamasını açar mısın'))
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
        with patch('modules.system_control.open_application',side_effect=AssertionError('uygulama açılmamalı')):
            with self.assertRaisesRegex(goal_tools.NotStarted,'yalnız ara adımı'):
                goal_tools.execute(runtime,'application',{'operation':'open','name':'Ayarlar'},{},identity)

    def test_goal_application_open_still_allows_plain_open_goal(self):
        profile=SimpleNamespace(slug='alice')
        runtime=SimpleNamespace(profile=profile,_cur_source='yazı',pc_profile=lambda:profile)
        identity={'request':'Hesap Makinesini aç','job_id':'j1','task_id':'s1'}
        opened=SimpleNamespace(ok=True,__str__=lambda self:'Hesap Makinesi açıldı')
        with patch('modules.system_control.open_application',return_value=opened):
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

    def test_one_off_task_is_not_mislearned_as_behaviour_rule(self):
        self.assertEqual(learning_feedback.rules_from_feedback('Ayarları aç ve Bluetooth’u kapat'),[])
        self.assertEqual(learning_feedback.rules_from_feedback('Bugün İstanbul sel durumuna bak'),[])


if __name__=='__main__':
    unittest.main()
