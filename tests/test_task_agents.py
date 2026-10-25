from pathlib import Path
import json
import tempfile
import sys
import types
import unittest
from unittest.mock import patch, Mock
from modules import task_agents as agents, browser_agent as browser, requests_state, task_workers


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(agents,'STORE',Path(self.tmp.name)/'tasks');p.start();self.addCleanup(p.stop)
        p=patch.object(browser,'STORE',Path(self.tmp.name)/'browser');p.start();self.addCleanup(p.stop)

    def test_plan_rejects_cycles_duplicate_ids_and_unsupported_shell(self):
        for tasks in [[{'id':'a','agent':'shell'}],[{'id':'a','agent':'writer','depends':['a']}],[{'id':'a','agent':'verify'},{'id':'a','agent':'verify'}]]:
            with self.assertRaises(ValueError):agents.validate(tasks)

    def test_actual_writer_saves_report_and_verifier_checks_real_output(self):
        from modules import nxapi
        tasks=[{'id':'write','agent':'writer','input':{'instruction':'write','filename':'rapor.md'}},
               {'id':'check','agent':'verify','depends':['write']}]
        with patch.object(nxapi,'FILES_DIR',Path(self.tmp.name)/'files'),patch.object(agents.llm,'ask',return_value='Gerçek rapor'):
            job=agents.execute('alice',tasks)
        self.assertEqual(job['state'],'done');path=Path(job['outputs']['write']['file'])
        self.assertEqual(path.read_text(),'Gerçek rapor')
        self.assertEqual(agents.recent('alice')['id'],job['id']);self.assertIsNone(agents.recent('bob'))
        path.unlink()
        with self.assertRaises(ValueError):agents.worker('alice',tasks[1],{'write':job['outputs']['write']})

    def test_failures_block_dependent_tasks_but_independent_work_runs(self):
        tasks=[{'id':'a','agent':'research'},{'id':'b','agent':'verify','depends':['a']},{'id':'c','agent':'research'}]
        work=Mock(side_effect=[ValueError('not available'),{'state':'done','text':'ok'}])
        with patch.object(agents,'worker',work):job=agents.execute('alice',tasks)
        self.assertEqual(job['state'],'incomplete');self.assertEqual(job['tasks'][1]['state'],'blocked');self.assertEqual(work.call_count,2)

    def test_research_specialist_returns_source_evidence_without_writing_an_artifact(self):
        source = 'Doğrulanmış kaynak metni enerji verimliliği bulgusunu açıklar. ' * 3
        answer = json.dumps({'supported': True, 'answer': 'Kaynak enerji verimliliği bulgusunu doğruluyor.',
                             'quotes': [source[:120]]})
        with patch('modules.browser.page_text', return_value=source), \
             patch('modules.model_wait.ask', return_value=answer), \
             patch.object(task_workers.privacy, 'blocked', return_value=None), \
             patch.object(task_workers.Path, 'write_text', side_effect=AssertionError('research dosya yazmamalı')) as write_text:
            result = agents.worker('alice', {'agent': 'research', 'input': {
                'url': 'https://example.org/source', 'question': 'Enerji verimliliği ne diyor?'
            }}, {})
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['source'], 'https://example.org/source')
        self.assertNotIn('file', result)
        self.assertNotIn('receipt', result)
        write_text.assert_not_called()

    def test_browser_approval_stops_dependents_and_resumes_exact_job(self):
        tasks=[{'id':'a','agent':'browser'},{'id':'b','agent':'verify','depends':['a']}]
        with patch.object(agents,'worker',return_value={'state':'approval','id':'123','message':'approve'}):job=agents.execute('alice',tasks)
        self.assertEqual(job['state'],'approval');self.assertEqual(job['tasks'][1]['state'],'queued')
        with self.assertRaises(ValueError):agents.resume('alice','wrong')
        image=Path(self.tmp.name)/'screen.png';image.write_bytes(b'actual test screenshot')
        with patch.object(browser,'run',return_value={'state':'done','steps':[{'op':'read','verified':True}], 'image':str(image),'page':{'title':'OK','url':'https://example.com','text':'sent'}}):
            result=agents.resume('alice','123')
        self.assertIn('done',result);self.assertEqual(agents.recent('alice')['state'],'done')

    def test_cancel_marks_job_and_never_runs_dependencies(self):
        with patch.object(agents,'worker',return_value={'state':'approval','id':'123'}):agents.execute('alice',[{'id':'a','agent':'browser'}])
        agents.handle('alice','tarayıcı iptal')
        self.assertEqual(agents.recent('alice')['state'],'cancelled')

    def test_cancellation_is_not_recorded_as_success(self):
        with patch.object(agents,'worker',side_effect=requests_state.Cancelled()):
            with self.assertRaises(requests_state.Cancelled):agents.execute('alice',[{'id':'a','agent':'verify'}])
        self.assertEqual(agents.recent('alice')['state'],'cancelled')

    def test_coder_requires_real_unlocked_development_mode(self):
        from modules import developer
        with patch.object(developer,'status',return_value={'enabled':False,'unlocked':False}),patch.object(developer,'handle') as handle:
            with self.assertRaises(ValueError):agents.worker('alice',{'agent':'coder','input':{'request':'x'}},{})
            handle.assert_not_called()

    def test_failed_coder_tests_cannot_close_job_as_done(self):
        from modules import developer
        status={'enabled': True, 'unlocked': True, 'draft_files': ['main.py'], 'draft_test_ok': False}
        with patch.object(developer, 'status', return_value=status), patch.object(developer, 'handle', return_value='Model bitti dedi'):
            with self.assertRaisesRegex(ValueError, 'testleri başarısız'):
                agents.worker('alice', {'agent': 'coder', 'input': {'request': 'düzelt'}}, {})

    def test_missing_coder_draft_keeps_underlying_explanation(self):
        from modules import developer
        status={'enabled':True,'unlocked':True,'draft_files':[],'draft_test_ok':None}
        with patch.object(developer,'status',return_value=status),patch.object(developer,'handle',return_value='Dosya üretilemedi; yalnız açıklama hazır.') as handle:
            with self.assertRaisesRegex(ValueError,'yalnız açıklama'):
                agents.worker('alice',{'agent':'coder','input':{'request':'örnek'}},{})
        self.assertTrue(handle.call_args.kwargs['require_draft'])

    def test_browser_failure_after_consumed_approval_releases_job_and_blocks_dependents(self):
        tasks=[{'id':'a','agent':'browser'},{'id':'b','agent':'verify','depends':['a']}]
        with patch.object(agents,'worker',return_value={'state':'approval','id':'123'}):agents.execute('alice',tasks)
        with patch.object(browser,'run',side_effect=RuntimeError('site timeout')):
            self.assertIn('incomplete',agents.resume('alice','123'))
        job=agents.recent('alice');self.assertEqual(job['tasks'][0]['state'],'failed');self.assertEqual(job['tasks'][1]['state'],'blocked')
        with patch.object(agents,'worker',return_value={'state':'done','text':'ok'}):
            self.assertEqual(agents.execute('alice',[{'id':'a','agent':'verify'}])['state'],'done')

    def test_browser_unavailable_preserves_unconsumed_approval_for_retry(self):
        import json
        with patch.object(agents,'worker',return_value={'state':'approval','id':'123'}):agents.execute('alice',[{'id':'a','agent':'browser'}])
        (browser._root('alice')/'pending.json').write_text(json.dumps({'id':'123'}))
        with patch.object(browser,'run',return_value={'state':'unavailable','message':'browser missing'}):agents.resume('alice','123')
        job=agents.recent('alice');self.assertEqual(job['state'],'approval');self.assertEqual(job['outputs']['a']['id'],'123')

    def test_running_job_is_visible_and_same_user_cannot_start_second_job(self):
        def work(owner,task,deps):
            self.assertEqual(agents.recent(owner)['state'],'running')
            with self.assertRaises(ValueError):agents.execute(owner,[{'id':'other','agent':'verify'}])
            return {'state':'done','text':'ok'}
        with patch.object(agents,'worker',side_effect=work):
            self.assertEqual(agents.execute('alice',[{'id':'first','agent':'verify'}])['state'],'done')

    def test_coder_model_exception_blocks_following_tasks(self):
        from modules import developer
        with patch.object(developer,'status',return_value={'enabled':True,'unlocked':True}),patch.object(developer,'handle',side_effect=RuntimeError('offline')):
            job=agents.execute('alice',[{'id':'code','agent':'coder','input':{'request':'fix'}},{'id':'check','agent':'verify','depends':['code']}])
        self.assertEqual(job['tasks'][0]['state'],'failed');self.assertEqual(job['tasks'][1]['state'],'blocked')

    def test_interrupted_job_is_not_reported_done(self):
        job={'id':'abc','state':'running','tasks':[{'id':'a','state':'running'}],'outputs':{}}
        agents._save(agents._root('alice'),job)
        self.assertEqual(agents.recent('alice')['state'],'interrupted')


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(browser,'STORE',Path(self.tmp.name));p.start();self.addCleanup(p.stop)

    def test_url_and_action_allowlist(self):
        for url in ['file:///etc/passwd','javascript:alert(1)','https://user:pass@example.com','data:text/html,test']:
            with self.assertRaises(ValueError):browser._url(url)
        for actions in [[{'op':'evaluate','script':'x'}],[{'op':'click','selector':'#send'}],[{'op':'press','selector':'#x','key':'Control+C','expect_text':'ok'}]]:
            with self.assertRaises(ValueError):browser.validate(actions)

    def page(self):
        page=Mock();page.url='https://example.com/form';page.title.return_value='Form'
        item=Mock();item.count.return_value=1;item.is_visible.return_value=True
        item.get_attribute.return_value=None;item.evaluate.return_value='button'
        page.locator.return_value=item;item.inner_text.return_value='Form Text'
        return page,item

    def test_consequential_click_waits_for_exact_plan_approval(self):
        page,item=self.page();root=browser._root('alice')
        actions=[{'op':'click','selector':'#send','expect_text':'sent'}]
        result=browser._execute(page,root,actions)
        self.assertEqual(result['state'],'approval');item.click.assert_not_called()
        stored=(root/'pending.json').read_text();self.assertIn('expect_text',stored)
        self.assertNotEqual(browser._root('alice'),browser._root('bob'))

    def test_changed_page_cannot_apply_approved_plan(self):
        page,item=self.page();approved={'digest':'old','signature':'button'}
        with self.assertRaises(ValueError):browser._execute(page,browser._root('alice'),[{'op':'click','selector':'#send','expect_text':'sent'}],approved)
        item.click.assert_not_called()

    def test_password_and_ambiguous_targets_never_typed(self):
        page,item=self.page();item.get_attribute.return_value='password'
        with self.assertRaises(ValueError):browser._execute(page,browser._root('alice'),[{'op':'fill','selector':'#x','value':'secret'}])
        item.fill.assert_not_called();item.count.return_value=2
        with self.assertRaises(ValueError):browser._target(page,'#x')

    def test_expected_result_missing_never_reports_success(self):
        page,item=self.page()
        actions=[{'op':'click','selector':'#send','expect_text':'Sent'}]
        approved={'digest':browser._digest(page),'signature':browser._signature(item)}
        with self.assertRaises(ValueError):browser._execute(page,browser._root('alice'),actions,approved)
        item.click.assert_called_once()

    def test_approval_consumed_before_side_effect_and_not_reusable(self):
        import json
        page,item=self.page();root=browser._root('alice')
        pending={'id':'valid','created':__import__('time').time(),'url':page.url,'digest':browser._digest(page),
                 'signature':browser._signature(item),'actions':[{'op':'click','selector':'#send','expect_text':'Sent'}]}
        (root/'pending.json').write_text(json.dumps(pending))
        context=Mock();context.pages=[page];pw=Mock();pw.chromium.launch_persistent_context.return_value=context
        manager=Mock();manager.__enter__=Mock(return_value=pw);manager.__exit__=Mock(return_value=False)
        def effect():
            self.assertFalse((root/'pending.json').exists())
            raise RuntimeError('site timeout after sending')
        item.click.side_effect=lambda **kwargs:effect()
        package=types.ModuleType('playwright');api=types.ModuleType('playwright.sync_api');api.sync_playwright=lambda:manager
        with patch.object(browser.privacy,'blocked',return_value=None),patch.dict(sys.modules,{'playwright':package,'playwright.sync_api':api}):
            with self.assertRaises(RuntimeError):browser.run('alice',approval='valid',headless=True)
            with self.assertRaises(ValueError):browser.run('alice',approval='valid',headless=True)
        item.click.assert_called_once();context.close.assert_called_once()

    def test_private_mode_does_not_even_import_browser(self):
        with patch.object(browser.privacy,'blocked',return_value='Web kapalı'):
            self.assertEqual(browser.run('alice',[{'op':'read'}])['state'],'blocked')


if __name__=='__main__':unittest.main()
