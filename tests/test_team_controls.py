"""Exact UI controls retain native ownership, approval and queue boundaries."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import team_center as team, goal_executor as goals, task_agents, task_queue, service_store, llm, requests_state
from web_tasks import WebTasks


class TeamControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for obj,key,value in [(team,'ROOT',self.root/'teams'),(goals,'STORE',self.root/'goals'),
                              (task_agents,'STORE',self.root/'tasks'),(service_store,'ROOT',self.root/'service'),
                              (goals,'_ACTIVE',set()),(goals,'_ACTIVE_JOBS',{}),(goals,'_CANCEL_REQUESTED',set())]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        self.profile=SimpleNamespace(slug='alice',name='Alice')
        self.runtime=SimpleNamespace(profile=self.profile,_cur_source='yazı',emit=Mock())
        self.bridge=WebTasks();self.bridge._runtime=SimpleNamespace(_p=lambda:self.profile,re=__import__('re'),engine=SimpleNamespace(submit=Mock(return_value=True)))

    def job(self,state='question',ident='a'*16):
        job={'id':ident,'owner':'alice','state':state,'created':1,'request':'Kullanıcının hedefi',
             'question':'Hangi kaynak?','goals':[{'text':'Rapor','state':'pending','evidence':[]}],
             'steps':[],'outputs':{}}
        goals._save(job);return job

    def plan(self):return [{'id':'source','agent':'research','input':{'url':'https://example.com'}}]

    def test_edit_disable_and_reenable_specialist_without_rewriting_work(self):
        entries=team.members('alice');rev=team.revision(entries)
        entries[0].update(name='Özel gündem',tags=['duyuru'],enabled=False)
        team.save_members('alice',entries,rev)
        self.assertNotEqual(team.assign('alice','research','duyuru')['id'],entries[0]['id'])
        rev=team.revision(team.members('alice'));entries[0]['enabled']=True
        team.save_members('alice',entries,rev)
        self.assertEqual(team.assign('alice','research','duyuru')['name'],'Özel gündem')
        with self.assertRaises(ValueError):team.save_members('alice',entries,rev)

    def test_pause_edit_resume_and_cancel_use_existing_queue_identity(self):
        qid=task_queue.enqueue('alice',self.plan(),'Gündem',0,300)
        task_queue.configure('alice',qid,operation='pause')
        with patch.object(task_agents,'execute') as work:
            task_queue.tick('alice');work.assert_not_called()
        task_queue.configure('alice',qid,operation='interval',repeat_seconds=3600)
        row=task_queue.rows('alice')[0];original=row['job_id']
        self.assertEqual((row['state'],row['repeat_seconds']),('paused',3600))
        task_queue.configure('alice',qid,operation='resume')
        self.assertEqual(task_queue.rows('alice')[0]['job_id'],original)
        task_queue.configure('alice',qid,operation='pause');task_queue.cancel('alice',qid)
        self.assertEqual(task_queue.rows('alice')[0]['state'],'cancelled')
        with self.assertRaises(ValueError):task_queue.configure('alice',qid,operation='resume')

    def test_live_queue_cannot_be_edited_or_revived_and_bad_intervals_fail(self):
        qid=task_queue.enqueue('alice',self.plan(),'Gündem',0,300)
        with service_store.database('alice') as db:db.execute("UPDATE queue SET state='running' WHERE id=?",(qid,))
        for op in ['pause','resume','interval']:
            with self.assertRaises(ValueError):task_queue.configure('alice',qid,operation=op,repeat_seconds=300)
        for interval in [True,1,-1,float('nan')]:
            with self.assertRaises(ValueError):task_queue.configure('alice',qid,operation='interval',repeat_seconds=interval)

    def test_answer_is_queued_with_exact_goal_and_revision_and_stale_question_fails_before_model(self):
        job=self.job();key=goals.control_key(job)
        self.bridge.team_control('goal',job['id'],'answer',key,'Resmî kaynak')
        command=self.bridge._runtime.engine.submit.call_args.args[0]
        self.assertIn(job['id'],command);self.assertIn(key,command)
        job['question']='Yeni soru';goals._save(job)
        with patch.object(llm,'ask') as model:
            with self.assertRaises(ValueError):goals.handle(self.runtime,command)
            model.assert_not_called()

    def test_old_goal_identity_never_controls_new_goal(self):
        old=self.job();key=goals.control_key(old);new=self.job(ident='b'*16)
        with self.assertRaises(ValueError):self.bridge.team_control('goal',old['id'],'approve',key)
        with patch.object(llm,'ask') as model:
            with self.assertRaises(ValueError):goals.run(self.runtime,'devam',resume=True,expected_job_id=old['id'],expected_control=key)
            model.assert_not_called()
        self.assertEqual(goals.latest('alice')['id'],new['id'])

    def test_changed_approval_payload_cannot_consume_old_ui_confirmation(self):
        job=self.job('approval');job.update(waiting='s1',approval_at=__import__('time').time())
        job['steps']=[{'id':'s1','tool':'action','state':'approval','input':{'action':'note_delete','params':{'nid':1}}}]
        job['outputs']={'s1':{'state':'approval','text':'1 numaralı notu sil'}};goals._save(job)
        key=goals.control_key(job)
        self.bridge.team_control('goal',job['id'],'approve',key)
        command=self.bridge._runtime.engine.submit.call_args.args[0]
        job['steps'][0]['input']['params']['nid']=2;goals._save(job)
        with patch.object(goals,'_record') as execute:
            with self.assertRaises(ValueError):goals.handle(self.runtime,command)
            execute.assert_not_called()

    def test_running_cancel_is_cooperative_and_scoped_to_exact_job(self):
        job=self.job('running')
        with goals._owned(self.runtime):
            goals._ACTIVE_JOBS['alice']=job['id']
            self.bridge.team_control('goal',job['id'],'cancel')
            with self.assertRaises(requests_state.Cancelled):goals._ensure(self.runtime,job)
            self.assertEqual(goals.latest('alice')['state'],'running','not prematurely claimed cancelled')
        self.assertFalse(goals._CANCEL_REQUESTED)

    def test_foreign_user_cannot_control_or_edit(self):
        job=self.job()
        self.profile=SimpleNamespace(slug='bob',name='Bob')
        with self.assertRaises(PermissionError):self.bridge.team_control('goal',job['id'],'cancel')
        with self.assertRaises(PermissionError):self.bridge.team_queue_edit('a'*16,'pause')

    def test_task_approval_changes_invalidate_the_snapshot_and_exact_receipt_is_queued(self):
        job={'id':'a'*12,'owner':'alice','state':'approval','created':1,'instruction':'Gönder',
             'tasks':[{'id':'s1','agent':'publish','state':'approval','input':{},'depends':[]}],
             'outputs':{'s1':{'state':'approval','id':'b'*16,'text':'İlk işlem'}}}
        task_agents._save(task_agents._root('alice'),job)
        old=goals.control_key(job)
        self.bridge.team_control('task',job['id'],'approve',old,approval_id='b'*16)
        self.assertEqual(self.bridge._runtime.engine.submit.call_args.args[0],'işlem onayla '+'b'*16)
        job['outputs']['s1'].update(id='c'*16,text='Başka işlem');task_agents._save(task_agents._root('alice'),job)
        self.bridge._runtime.engine.submit.reset_mock()
        with self.assertRaises(ValueError):self.bridge.team_control('task',job['id'],'approve',old,approval_id='b'*16)
        self.bridge._runtime.engine.submit.assert_not_called()


if __name__=='__main__':unittest.main()
