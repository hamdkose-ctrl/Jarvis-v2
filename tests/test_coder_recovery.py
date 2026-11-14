"""Actual draft files, Python tests and delivery; only provider/network and full suite are substituted."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import developer as dev, llm, nxapi, smart_router as router, task_agents as agents, task_results
from provider_fixture import fresh_bundle


TESTS = '''import unittest
from sample import topla
class AdditionTests(unittest.TestCase):
    def test_positive(self): self.assertEqual(topla(2,3),5)
    def test_negative(self): self.assertEqual(topla(-1,1),0)
'''


class CoderRecoveryTests(unittest.TestCase):
    def setUp(self):
        fresh_bundle(self)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.project=self.root/'project';self.project.mkdir()
        (self.project/'original.py').write_text('untouched = True\n')
        for obj, name, value in [(dev,'PROJECT',self.project),(dev,'STORE',self.root/'dev'),
            (dev,'_AUTH',set()),(agents,'STORE',self.root/'tasks'),(nxapi,'FILES_DIR',self.root/'files'),
            (router,'_STORE',self.root/'router'),(router,'_HEALTH',{})]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        for obj,name,value in [(router.privacy,'mode','normal'),(llm,'provider','auto'),
             (llm,'current_user','alice'),(llm,'user_key','gem-key'),(llm,'user_groq_key','groq-key')]:
            p=patch.object(obj,name,return_value=value);p.start();self.addCleanup(p.stop)
        dev.unlock('alice','test-password');dev.enable('alice');router.configure('alice',True)
        now=router.time.time()
        for provider, model in [('gemini',llm.active_model('alice')),('groq',llm.groq_model())]:
            router.set_free_tier_evidence(
                'alice',provider=provider,model=model,free_tier_verified=True,source='test-fixture',
                evidence_ref='test://official-free-tier',verified_at=now,ttl_seconds=3600,
                eligibility='eligible',quota_state='available',quota_remaining=10,
                hard_stop_guaranteed=True,verification_status='verified',reason='coder recovery fixture')
        llm.take_route()
        self.addCleanup(llm.take_route)

    def plan(self):
        return [{'id':'code','agent':'coder','input':{'request':'Yeni Python dosyasında topla fonksiyonu ve testlerini oluştur; kaynaklara uygulama.'}},
                {'id':'verify','agent':'verify','depends':['code']}]

    def calls(self):
        return [{'tool':'read','path':'sample.py'},
                {'tool':'stage','path':'sample.py','content':'def topla(a,b):\n return a-b\n'},
                {'tool':'read','path':'test_sample.py'},
                {'tool':'stage','path':'test_sample.py','content':TESTS},
                {'tool':'test'},
                {'tool':'edit','path':'sample.py','old':'return a-b','new':'return a+b'},
                {'tool':'finish','message':'Hazır.'},{'tool':'finish','message':'Hazır.'}]

    def test_bad_provider_then_real_test_failure_repaired_and_files_delivered(self):
        local = patch.object(llm, '_ollama_effective_model', return_value='local-test')
        local.start(); self.addCleanup(local.stop)
        responses=iter(self.calls());seen=[];prompts=[]
        def send(selected,prompt,system,tokens,history,*,model=None):
            seen.append(selected);prompts.append(prompt)
            text='İşte kod açıklaması' if selected=='groq' else json.dumps(next(responses))
            return llm._timed(selected,lambda:text)
        with patch.object(llm,'_send_provider',side_effect=send),patch.object(dev,'_test',return_value=(True,'Full suite passed')) as suite:
            job=agents.execute('alice',self.plan())
        self.assertEqual(job['state'],'done',agents.render(job))
        self.assertEqual(seen[:2],['groq','ollama'])
        self.assertTrue(any('AssertionError' in prompt for prompt in prompts))
        self.assertEqual(suite.call_count,1)  # broken new-code test fails before expensive full suite
        output=job['outputs']['code']
        self.assertEqual(len(output['files']),2)
        self.assertIn('Ran 2 tests',Path(output['test_log']).read_text())
        self.assertIn('return a+b',Path(output['files'][0]['file']).read_text())
        self.assertFalse((self.project/'sample.py').exists())
        self.assertEqual((self.project/'original.py').read_text(),'untouched = True\n')
        self.assertNotIn('Cevap: Gemini',str(llm.take_route()))
        self.assertIn('Dosya:',agents.render_summary(job))
        self.assertTrue(task_results.verify(output,owner='alice'))
        with self.assertRaises(PermissionError):task_results.verify(output,owner='bob')
        Path(output['files'][0]['file']).write_text('changed')
        with self.assertRaises(ValueError):task_results.verify(output,owner='alice')

    def test_old_successful_draft_does_not_complete_new_request(self):
        state=dev._load('alice');dev._stage(state,'old.py','old = 1\n')
        state['draft_test']={'ok':True,'signature':dev._draft_signature(state),'log':'old tests'}
        dev._save('alice',state)
        with patch.object(llm,'ask',return_value=json.dumps({'tool':'finish','message':'Yaptım'})):
            job=agents.execute('alice',self.plan())
        self.assertEqual(job['state'],'incomplete')
        self.assertEqual(job['tasks'][1]['state'],'blocked')
        self.assertFalse(list((self.root/'files').glob('**/*.py')))
        self.assertEqual(dev._load('alice')['draft']['old.py']['content'],'old = 1\n')

    def test_empty_and_skipped_new_code_tests_are_not_success(self):
        state=dev._load('alice')
        for content in ('import unittest\n', 'import unittest\nclass T(unittest.TestCase):\n @unittest.skip("skip")\n def test_empty(self): pass\n',
                        'import unittest\nclass T(unittest.TestCase):\n @unittest.expectedFailure\n def test_known_wrong(self): self.assertEqual(1,2)\n'):
            dev._stage(state,'test_empty.py',content)
            with patch.object(dev,'_test') as suite:
                result=dev._test_draft('alice',state,code_paths={'test_empty.py'})
            self.assertFalse(result['ok']);suite.assert_not_called()
        with patch.object(dev,'_test') as suite:
            result=dev._test_draft('alice',state,code_paths={'sample.py'})
        self.assertFalse(result['ok']);suite.assert_not_called()

    def test_test_cannot_mutate_candidate_to_pass_and_deliver_untested_draft(self):
        for name in ('sample.py','build/sample.py'):
            state=dev._load('alice')
            dev._stage(state,name,'def topla(a,b):\n return a-b\n')
            mutation='from pathlib import Path\nPath('+repr(name)+').write_text("def topla(a,b):\\n return a+b\\n")\n'
            tests=TESTS.replace('from sample', 'from '+name[:-3].replace('/','.'))
            dev._stage(state,'test_sample.py',mutation+tests)
            with patch.object(dev,'_test') as suite:
                result=dev._test_draft('alice',state,code_paths={'test_sample.py',name})
            self.assertFalse(result['ok']);suite.assert_not_called()
            self.assertIn('aday kaynak dosyalarını değiştirdi',result['log'])
            self.assertIn('return a-b',state['draft'][name]['content'])

    def test_manual_test_invalidates_pre_test_resume_checkpoint(self):
        request=self.plan()[0]['input']['request']
        with patch.object(llm,'ask',side_effect=RuntimeError('offline')):
            agents.execute('alice',self.plan())
        self.assertTrue(dev.code_retry_safe('alice',request))
        state=dev._load('alice');dev._stage(state,'example.py','value = 1\n');dev._save('alice',state)
        with patch.object(dev,'_test',return_value=(True,'OK')):
            dev.handle('alice','taslağı test et')
        self.assertFalse(dev.code_retry_safe('alice',request))

    def test_pre_test_provider_failure_can_resume_saved_job_but_post_test_failure_cannot(self):
        with patch.object(llm,'ask',side_effect=RuntimeError('offline')):
            job=agents.execute('alice',self.plan())
        self.assertTrue(job['outputs']['code']['retry_safe'])
        with patch.object(llm,'ask',side_effect=[json.dumps(c) for c in self.calls()]), \
             patch.object(dev,'_test',return_value=(True,'Full suite passed')):
            resumed=agents.continue_job('alice',job['id'])
        self.assertEqual(resumed['state'],'done',agents.render(resumed))
        with patch.object(llm,'ask',side_effect=[json.dumps(c) for c in self.calls()[:5]]+[RuntimeError('offline')]):
            failed=agents.execute('alice',self.plan())
        self.assertFalse(failed['outputs']['code']['retry_safe'])
        with self.assertRaisesRegex(ValueError,'dış işlem'):
            agents.continue_job('alice',failed['id'])

    def test_cancellation_and_missing_provider_never_deliver_false_success(self):
        from modules import requests_state
        with patch.object(llm,'ask',side_effect=requests_state.Cancelled('stop')):
            with self.assertRaises(requests_state.Cancelled):agents.execute('alice',self.plan())
        job=agents.recent('alice')
        self.assertNotEqual(job['state'],'done')
        self.assertFalse(list((self.root/'files').glob('**/*.py')))

    def test_manual_provider_can_repair_schema_without_silently_switching_provider(self):
        def validate(text): dev._tool_call(text)
        from provider_fixture import routed_plan
        with routed_plan(provider='ollama',model='local-fixture'),patch.object(llm,'provider',return_value='ollama'), \
             patch.object(llm,'_send_provider',side_effect=['duz yazi','{"tool":"list"}']) as send:
            result=llm.ask('incele','schema',validator=validate)
        self.assertEqual(dev._tool_call(result)['tool'],'list')
        self.assertEqual([c.args[0] for c in send.call_args_list],['ollama','ollama'])   # elle seçilen yerel sağlayıcı sessizce değişmez

    def test_new_non_addition_program_uses_same_generic_delivery_flow(self):
        calls=[{'tool':'read','path':'names.py'},
            {'tool':'stage','path':'names.py','content':'def normalize(text):\n return " ".join(text.split()).casefold()\n'},
            {'tool':'read','path':'test_names.py'},
            {'tool':'stage','path':'test_names.py','content':'import unittest\nfrom names import normalize\nclass T(unittest.TestCase):\n def test_names(self): self.assertEqual(normalize("  HAMDI   KOSE  "),"hamdi kose")\n'},
            {'tool':'finish','message':'Hazır'}, {'tool':'finish','message':'Hazır'}]
        with patch.object(llm,'ask',side_effect=[json.dumps(c) for c in calls]), \
             patch.object(dev,'_test',return_value=(True,'Full suite passed')):
            output=agents.worker('alice',{'agent':'coder','input':{'request':'İsimlerde boşlukları temizleyen fonksiyon ve testlerini oluştur.'}}, {})
        self.assertIn('normalize',Path(output['file']).read_text())
        self.assertIn('Ran 1 test',Path(output['test_log']).read_text())
        Path(output['test_log']).write_text('tampered')
        with self.assertRaises(ValueError):task_results.verify(output,owner='alice')

    def test_delivery_rechecks_request_source_and_lock(self):
        request=self.plan()[0]['input']['request']
        with patch.object(llm,'ask',side_effect=[json.dumps(c) for c in self.calls()]), \
             patch.object(dev,'_test',return_value=(True,'Full suite passed')):
            job=agents.execute('alice',self.plan())
        self.assertEqual(job['state'],'done')
        with self.assertRaises(ValueError):dev.deliver_code('alice','different request')
        (self.project/'sample.py').write_text('source changed after test')
        with self.assertRaisesRegex(ValueError,'testten sonra değişmiş'):dev.deliver_code('alice',request)
        dev._AUTH.clear()
        with self.assertRaises(PermissionError):dev.deliver_code('alice',request)

    def test_no_eligible_provider_does_not_call_network_or_deliver_files(self):
        empty={'candidates':[],'skipped':[]}
        with patch.object(router,'selection',return_value=empty), \
             patch.object(llm,'_send') as send:
            job=agents.execute('alice',self.plan())
        self.assertEqual(job['state'],'incomplete');send.assert_not_called()
        self.assertFalse(list((self.root/'files').glob('**/*.py')))

    def test_new_code_test_timeout_is_failed_evidence(self):
        import subprocess
        state=dev._load('alice');dev._stage(state,'test_timeout.py','import unittest\n')
        with patch.object(dev.subprocess,'run',side_effect=subprocess.TimeoutExpired('unittest',30)), \
             patch.object(dev,'_test') as suite:
            result=dev._test_draft('alice',state,code_paths={'test_timeout.py'})
        self.assertFalse(result['ok']);suite.assert_not_called()


class GroqModelRecoveryTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(router,'settings',return_value={'cloud_free_confirmed':True});p.start();self.addCleanup(p.stop)
        for name,value in [('GROQ_MODELS',['a','b','c']),('_fallback_states',{}),('_rate_limited',{})]:
            p=patch.object(llm,name,value);p.start();self.addCleanup(p.stop)
        for name,value in [('groq_model','a'),('current_user','alice'),('user_groq_key','alice-secret')]:
            p=patch.object(llm,name,return_value=value);p.start();self.addCleanup(p.stop)
        llm.take_route();self.addCleanup(llm.take_route)

    def response(self,code,text='answer'):
        from unittest.mock import Mock
        response=Mock(status_code=code)
        response.json.return_value={'choices':[{'message':{'content':text}}],'error':{'message':'PRIVATE body'}}
        return response

    def test_direct_groq_uses_one_selected_model_and_owner_credentials(self):
        with patch.object(llm.requests,'post',return_value=self.response(200)) as post:
            self.assertEqual(llm._groq([{'role':'user','content':'x'}],'',100),'answer')
        self.assertEqual([c.kwargs['json']['model'] for c in post.call_args_list],['a'])
        with patch.object(llm,'current_user',return_value='bob'),patch.object(llm,'user_groq_key',return_value='bob-secret') as key, \
             patch.object(llm.requests,'post',return_value=self.response(200)) as post:
            llm._groq([{'role':'user','content':'x'}],'',100)
        key.assert_called_once_with('bob')
        self.assertEqual(post.call_args.kwargs['json']['model'],'a')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'],'Bearer bob-secret')
        self.assertNotIn('secret',str(llm.take_route()))

    def test_rejected_credentials_never_retry_models_and_error_body_is_not_exposed(self):
        with patch.object(llm.requests,'post',return_value=self.response(403)) as post:
            with self.assertRaises(llm.CloudError) as error:llm._groq([],'',100)
        self.assertEqual(post.call_count,1);self.assertNotIn('PRIVATE',str(error.exception))
        with patch.object(llm.requests,'post',return_value=self.response(429)) as post:
            with self.assertRaises(llm.CloudError) as error:llm._groq([],'',100)
        self.assertEqual(post.call_count,1);self.assertNotIn('PRIVATE',str(error.exception))

    def test_transient_error_and_empty_reply_do_not_start_hidden_retry(self):
        with patch.object(llm.requests,'post',return_value=self.response(500)) as post:
            with self.assertRaises(llm.CloudError): llm._groq([],'',100)
        self.assertEqual(post.call_count,1)
        with patch.object(llm.requests,'post',return_value=self.response(200,' ')) as post:
            with self.assertRaises(llm.CloudError): llm._groq([],'',100)
        self.assertEqual(post.call_count,1)

    def test_network_outage_does_not_repeat_requests_for_every_model(self):
        with patch.object(llm.time,'sleep'),patch.object(llm.requests,'post',side_effect=llm.requests.ReadTimeout('PRIVATE')) as post:
            with self.assertRaises(llm.CloudError) as error:llm._groq([],'',100)
        self.assertEqual(post.call_count,1);self.assertNotIn('PRIVATE',str(error.exception))

    def test_model_alternatives_require_this_users_free_account_confirmation(self):
        with patch.object(router,'settings',return_value={'cloud_free_confirmed':False}), \
             patch.object(llm.requests,'post',return_value=self.response(429)) as post:
            with self.assertRaises(llm.CloudError):llm._groq([],'',100)
        self.assertEqual(post.call_count,1)


if __name__=='__main__':unittest.main()