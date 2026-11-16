"""Crash recovery, evidence integrity and owner isolation; no live services."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from modules import task_agents as agents, browser_agent as browser, requests_state
from writer_consent_fixture import native_writer_after_consent


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for obj,name,value in [(agents,'STORE',self.root/'tasks'),(browser,'STORE',self.root/'browser')]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        agents._ACTIVE.clear();agents._CANCEL_REQUESTED.clear()

    def plan(self):
        return [{'id':'read','agent':'research','input':{'url':'https://example.com'}},
                {'id':'write','agent':'research','depends':['read'],'input':{'url':'https://example.com/report'}},
                {'id':'verify','agent':'verify','depends':['write']}]

    def test_crash_resumes_only_unfinished_safe_steps(self):
        calls=[]
        def work(owner,task,deps):
            calls.append(task['id'])
            if task['id']=='write':raise KeyboardInterrupt('process vanished')
            return {'state':'done','text':'source'}
        with patch.object(agents,'worker',side_effect=work):
            with self.assertRaises(KeyboardInterrupt):agents.execute('alice',self.plan(),'Araştır')
        saved=agents.recent('alice');self.assertEqual(saved['state'],'interrupted')
        self.assertEqual(saved['tasks'][0]['state'],'done')
        resumed=[]
        def complete(owner,task,deps):
            resumed.append(task['id']);return {'state':'done','text':'ok'}
        with patch.object(agents,'worker',side_effect=complete):result=agents.continue_job('alice',saved['id'])
        self.assertEqual(resumed,['write','verify']);self.assertEqual(result['state'],'done')
        self.assertEqual(result['tasks'][1]['attempts'],2)
        with patch.object(agents,'worker') as run:agents.continue_job('alice',saved['id']);run.assert_not_called()

    def test_unknown_browser_effect_is_never_replayed(self):
        with patch.object(agents,'worker',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):agents.execute('alice',[{'id':'send','agent':'browser'}])
        job=agents.recent('alice')
        with patch.object(agents,'worker') as run:
            with self.assertRaisesRegex(ValueError,'dış işlem'):agents.continue_job('alice',job['id'])
            run.assert_not_called()

    def test_failure_retry_does_not_repeat_completed_independent_work(self):
        tasks=[{'id':'a','agent':'research'},{'id':'b','agent':'research','depends':['a']},{'id':'c','agent':'research'}]
        with patch.object(agents,'worker',side_effect=[RuntimeError('offline'),{'state':'done','text':'c'}]):job=agents.execute('alice',tasks)
        calls=[]
        with patch.object(agents,'worker',side_effect=lambda o,t,d:(calls.append(t['id']) or {'state':'done','text':'ok'})):
            self.assertEqual(agents.continue_job('alice',job['id'])['state'],'done')
        self.assertEqual(calls,['a','b'])

    def test_changed_or_missing_artifact_blocks_dependents_on_resume(self):
        report=self.root/'report.md';report.write_text('original')
        digest=hashlib.sha256(report.read_bytes()).hexdigest()
        tasks=[{'id':'write','agent':'research'},{'id':'verify','agent':'verify','depends':['write']}]
        with patch.object(agents,'worker',side_effect=[{'state':'done','file':str(report),'sha256':digest},KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):agents.execute('alice',tasks)
        job=agents.recent('alice');report.write_text('tampered')
        with patch.object(agents,'worker') as work:
            with self.assertRaisesRegex(ValueError,'değişmiş'):agents.continue_job('alice',job['id'])
            work.assert_not_called()
        with self.assertRaises(ValueError):agents.worker('alice',{'agent':'verify'},{'write':job['outputs']['write']})

    def test_owner_cannot_read_cancel_resume_or_recall_another_job(self):
        with patch.object(agents,'worker',return_value={'state':'done','text':'Alice only'}):job=agents.execute('alice',[{'id':'a','agent':'research'}],'Gizli rapor')
        for action in (agents.continue_job,agents.cancel_job,agents._load):
            with self.assertRaises(ValueError):action('bob',job['id'])
        self.assertEqual(agents.history('bob'),[]);self.assertEqual(agents.memory_context('bob','Gizli rapor'),'')

    def test_owner_model_context_restores_even_after_abrupt_failure(self):
        token=agents.llm._key_context.set('bob')
        try:
            def work(owner,task,deps):
                self.assertEqual(agents.llm.current_user(),'alice');raise KeyboardInterrupt
            with patch.object(agents,'worker',side_effect=work):
                with self.assertRaises(KeyboardInterrupt):agents.execute('alice',[{'id':'a','agent':'research'}])
            self.assertEqual(agents.llm.current_user(),'bob')
        finally:agents.llm._key_context.reset(token)

    def test_cancel_while_worker_runs_cannot_be_overwritten_by_done(self):
        started=threading.Event();release=threading.Event();failures=[]
        def work(owner,task,deps):started.set();release.wait(3);return {'state':'done','text':'late result'}
        def run():
            try:agents.execute('alice',[{'id':'a','agent':'research'},{'id':'b','agent':'writer','depends':['a']}])
            except requests_state.Cancelled:failures.append('cancelled')
        with patch.object(agents,'worker',side_effect=work) as mocked:
            thread=threading.Thread(target=run);thread.start();self.assertTrue(started.wait(2))
            job=agents.cancel_job('alice');release.set();thread.join(3);self.assertFalse(thread.is_alive())
            self.assertEqual(mocked.call_count,1)
        self.assertEqual(failures,['cancelled']);self.assertEqual(agents.recent('alice')['state'],'cancelled')
        with patch.object(agents,'worker') as mocked:agents.continue_job('alice',job['id']);mocked.assert_not_called()

    def test_atomic_storage_failure_does_not_start_worker(self):
        with patch.object(agents.os,'replace',side_effect=OSError('disk full')),patch.object(agents,'worker') as work:
            with self.assertRaises(OSError):agents.execute('alice',[{'id':'a','agent':'research'}])
            work.assert_not_called()
        self.assertNotIn('alice',agents._ACTIVE)

    def test_input_plan_is_not_mutated_and_invalid_id_cannot_escape(self):
        tasks=[{'id':'a','agent':'research','input':{'question':'x'}}]
        def work(owner,task,deps):task['input']['question']='changed';return {'state':'done','text':'ok'}
        with patch.object(agents,'worker',side_effect=work):agents.execute('alice',tasks)
        self.assertEqual(tasks[0]['input']['question'],'x')
        for value in ('../bob','x/y','',None):
            with self.assertRaises(ValueError):agents._load('alice',value)

    def test_no_planner_call_when_interrupted_job_waits(self):
        with patch.object(agents,'worker',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):agents.execute('alice',[{'id':'a','agent':'research'}])
        with patch.object(agents.llm,'ask') as model:
            reply=agents.handle('alice','görev: yeni bir rapor hazırla');model.assert_not_called()
        self.assertIn('açık görevi',reply)

    def test_cancel_removes_only_this_jobs_pending_browser_approval(self):
        with patch.object(agents,'worker',return_value={'state':'approval','id':'exact'}):
            job=agents.execute('alice',[{'id':'a','agent':'browser'}])
        path=browser._root('alice')/'pending.json';path.write_text(json.dumps({'id':'exact'}))
        agents.cancel_job('alice',job['id']);self.assertFalse(path.exists())
        with patch.object(agents,'worker',return_value={'state':'done','text':'ok'}):
            self.assertEqual(agents.execute('alice',[{'id':'b','agent':'research'}])['state'],'done')

    def test_cancel_does_not_remove_unrelated_browser_plan(self):
        with patch.object(agents,'worker',return_value={'state':'approval','id':'exact'}):
            job=agents.execute('alice',[{'id':'a','agent':'browser'}])
        path=browser._root('alice')/'pending.json';path.write_text(json.dumps({'id':'other'}))
        agents.cancel_job('alice',job['id']);self.assertEqual(json.loads(path.read_text())['id'],'other')

    def test_missing_success_record_cannot_be_reported_as_completed(self):
        agents._save(agents._root('alice'),{'id':'corrupt','state':'done','tasks':[{'id':'a','agent':'research','state':'done'}],'outputs':{}})
        with self.assertRaisesRegex(ValueError,'başarı kaydı'):agents.recent('alice')

    def test_request_owner_mismatch_stops_before_planning_or_work(self):
        token=requests_state._current.set(('bob','request'))
        try:
            with patch.object(agents.llm,'ask') as model,patch.object(agents,'worker') as work:
                with self.assertRaises(PermissionError):agents.handle('alice','görev: araştır')
                with self.assertRaises(PermissionError):agents.execute('alice',[{'id':'a','agent':'research'}])
                model.assert_not_called();work.assert_not_called()
        finally:requests_state._current.reset(token)

    def test_actual_writer_digest_and_empty_result_rejected(self):
        from modules import nxapi
        with patch.object(nxapi,'FILES_DIR',self.root/'files'),patch.object(agents.llm,'ask',return_value='Rapor'),native_writer_after_consent():
            output=agents.worker('alice',{'agent':'writer','input':{'instruction':'write'}},{})
        self.assertTrue(agents._artifact(output));self.assertEqual(len(output['sha256']),64)
        with patch.object(agents.llm,'ask',return_value=''),native_writer_after_consent():
            with self.assertRaisesRegex(ValueError,'boş'):agents.worker('alice',{'agent':'writer','input':{'instruction':'write'}},{})

    def test_history_and_retrieval_remain_after_reload(self):
        with patch.object(agents,'worker',return_value={'state':'done','text':'Kontrollü kaynak özeti'}):job=agents.execute('alice',[{'id':'a','agent':'research'}],'Robot araştırması')
        agents._ACTIVE.clear()
        data=agents.memory_context('alice','Robot araştırması');self.assertIn(job['id'],data)
        self.assertIn('Kontrollü kaynak',data);self.assertEqual(agents.memory_context('alice','alakasız konu'),'')
        self.assertIn(job['id'],agents.handle('alice','görev geçmişi'))
        self.assertIn('1/1',agents.handle('alice','görev durumu '+job['id']))

if __name__=='__main__':unittest.main()
