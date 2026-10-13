import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from modules import task_agents as agents, llm, browser_agent


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for mod,name in ((agents,'tasks'),(browser_agent,'browser')):
            p=patch.object(mod,'STORE',Path(self.tmp.name)/name);p.start();self.addCleanup(p.stop)

    def test_independent_roles_overlap_keep_owner_and_join_before_dependent(self):
        barrier=threading.Barrier(2);contexts=[];lock=threading.Lock()
        tasks=[{'id':'a','agent':'research'},{'id':'b','agent':'research'}, {'id':'join','agent':'verify','depends':['a','b']}]
        def work(owner,task,deps):
            if task['id']!='join':barrier.wait(timeout=2)
            else:self.assertEqual(set(deps),{'a','b'})
            with lock:contexts.append((owner,llm._key_context.get()))
            return {'state':'done','text':task['id']}
        token=llm._key_context.set('previous')
        try:
            with patch.object(agents,'worker',side_effect=work):job=agents.execute('alice',tasks,parallel=True)
            self.assertEqual(llm._key_context.get(),'previous')
        finally:llm._key_context.reset(token)
        self.assertEqual(job['state'],'done');self.assertEqual(contexts,[('alice','alice')]*3)
        self.assertEqual(job['strategy'],'parallel')

    def test_failure_blocks_its_dependents_but_preserves_independent_result(self):
        tasks=[{'id':'a','agent':'research'},{'id':'b','agent':'research'},{'id':'blocked','agent':'verify','depends':['a']}]
        def work(owner,task,deps):
            if task['id']=='a':raise RuntimeError('offline')
            return {'state':'done','text':'ok'}
        with patch.object(agents,'worker',side_effect=work):job=agents.execute('alice',tasks,parallel=True)
        self.assertEqual(job['state'],'incomplete');self.assertEqual(job['tasks'][1]['state'],'done');self.assertEqual(job['tasks'][2]['state'],'blocked')

    def test_external_or_code_worker_rejected_before_any_work(self):
        with patch.object(agents,'worker') as worker:
            with self.assertRaises(ValueError):agents.execute('alice',[{'id':'a','agent':'coder','input':{'request':'fix'}}],parallel=True)
            worker.assert_not_called()

    def test_completed_parallel_job_does_not_repeat_roles(self):
        with patch.object(agents,'worker',return_value={'state':'done'}):job=agents.execute('alice',[{'id':'a','agent':'verify'}],parallel=True)
        with patch.object(agents,'worker') as worker:
            self.assertEqual(agents.continue_job('alice',job['id'])['state'],'done');worker.assert_not_called()


if __name__=='__main__':unittest.main()
