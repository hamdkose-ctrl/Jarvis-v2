"""Team registry and real journal integration; no live accounts/model/device calls."""
import base64
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import team_center as team, goal_executor, task_agents, task_queue, llm, service_store, task_results
from web_tasks import WebTasks


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for obj,key,value in [(team,'ROOT',self.root/'teams'),(goal_executor,'STORE',self.root/'goals'),
                              (task_agents,'STORE',self.root/'tasks'),(service_store,'ROOT',self.root/'services')]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        self.bridge=WebTasks();self.bridge._runtime=SimpleNamespace(_p=lambda:SimpleNamespace(slug='alice'),re=__import__('re'))

    def test_defaults_are_extensible_but_cannot_install_code_or_grant_permissions(self):
        entries=team.members('alice')
        self.assertTrue({'finance','social','store'}.issubset({e['id'] for e in entries}))
        entries.append({'id':'logistics','name':'Lojistik','tags':['kargo'],'tools':['research','writer']})
        team.save_members('alice',entries)
        self.assertEqual(team.assign('alice','research','kargo durumunu araştır')['id'],'logistics')
        self.assertEqual(team.members('alice'),entries)
        for extra in [{'url':'https://attacker.invalid'},{'permission':True}]:
            bad=copy.deepcopy(entries);bad[-1].update(extra)
            with self.assertRaises(ValueError):team.save_members('alice',bad)
        bad=copy.deepcopy(entries);bad[-1]['tools']=['shell']
        with self.assertRaises(ValueError):team.save_members('alice',bad)
        with self.assertRaises(ValueError):team.assign('alice','publish','',preferred='logistics')

    def test_foreign_owner_and_traversal_are_rejected(self):
        for owner in ['bob','../alice','',None]:
            with self.assertRaises((PermissionError,ValueError)):team.members(owner)
        with self.assertRaises((PermissionError,ValueError)):team.snapshot('bob')

    def test_snapshot_reads_real_jobs_and_queue_and_survives_one_bad_journal(self):
        root=goal_executor._root('alice')
        job={'id':'a'*16,'owner':'alice','created':1,'state':'running','request':'Fatura raporu',
             'goals':[{'text':'Rapor','state':'pending'}],
             'steps':[{'id':'s1','tool':'document','state':'running','depends':[]}],'outputs':{}}
        (root/(job['id']+'.json')).write_text(json.dumps(job))
        (root/'bad.json').write_text('{')
        plan=[{'id':'a','agent':'research','input':{'url':'https://example.com'}}]
        qid=self.bridge.team_schedule(plan,'Kaynağı takip et',0,300)
        with patch.object(llm,'ask',side_effect=AssertionError('snapshot cannot call model')):
            snapshot=self.bridge.team_snapshot()
        self.assertEqual(snapshot['jobs'][0]['steps'][0]['specialist']['id'],'jarvis')
        self.assertTrue(snapshot['warnings']);self.assertEqual(snapshot['queue'][0]['id'],qid)
        self.assertEqual(snapshot['jobs'][0]['state'],'interrupted')
        self.bridge.team_queue_cancel(qid)
        self.assertEqual(task_queue.rows('alice')[0]['state'],'cancelled')

    def test_another_active_job_does_not_revive_an_old_running_journal(self):
        root=goal_executor._root('alice')
        for ident in ['a'*16,'b'*16]:
            job={'id':ident,'owner':'alice','created':1,'state':'running','request':'Rapor',
                 'steps':[{'id':'s1','tool':'writer','state':'running','depends':[]}],'outputs':{}}
            (root/(ident+'.json')).write_text(json.dumps(job))
        with patch.object(goal_executor,'_ACTIVE',{'alice'}),patch.object(goal_executor,'_ACTIVE_JOBS',{'alice':'b'*16}):
            states={j['id']:j for j in team.snapshot('alice')['jobs']}
        self.assertEqual(states['a'*16]['state'],'interrupted')
        self.assertEqual(states['a'*16]['steps'][0]['state'],'interrupted')
        self.assertEqual(states['b'*16]['state'],'running')

    def test_goal_records_assignment_and_verifies_actual_file_and_changed_file_fails(self):
        from modules import nxapi
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'),_cur_source='yazı',emit=Mock())
        replies=[{'action':'plan','goals':['Finans raporu']},
                 {'action':'tool','goal':0,'tool':'writer','input':{'instruction':'Finans raporu yaz'}},
                 'Kaynak verilmediği için güncel finans verisi bulunmuyor.',
                 {'action':'complete','goal':0,'evidence':['s1']},{'action':'finish'}]
        with patch.object(nxapi,'FILES_DIR',self.root/'files'),patch.object(llm,'ask',side_effect=[json.dumps(x) if isinstance(x,dict) else x for x in replies]):
            from writer_consent_fixture import run_with_explicit_writer_approval
            run_with_explicit_writer_approval(runtime,'Finans raporu dosyası oluştur')
        job=goal_executor.latest('alice')
        self.assertEqual(job['state'],'done');self.assertEqual(job['steps'][0]['specialist']['id'],'finance')
        self.assertTrue(self.bridge.team_verify('goal',job['id'])['ok'])
        self.assertTrue((goal_executor._root('alice')/(job['id']+'.execution.json')).exists())
        self.assertEqual([j['id'] for j in team.snapshot('alice')['jobs']],[job['id']])
        file = Path(job['outputs']['s1']['file'])
        with patch.object(nxapi, 'FILES_DIR', self.root / 'files'):
            saved = self.bridge.team_artifact('goal', job['id'], 's1', file.name)
            self.assertEqual(saved['owner'], 'alice')
            self.assertEqual(base64.b64decode(saved['content']), file.read_bytes())
            with self.assertRaises(ValueError):
                self.bridge.team_artifact('goal', job['id'], 's1', '../' + file.name)
            with self.assertRaises(ValueError):
                self.bridge.team_artifact('goal', job['id'], 's2', file.name)
            with self.assertRaises((PermissionError, ValueError, OSError)):
                team.artifact('bob', 'goal', job['id'], 's1', file.name)
            file.write_text('changed')
            with self.assertRaises(ValueError):
                self.bridge.team_artifact('goal', job['id'], 's1', file.name)
        self.assertFalse(self.bridge.team_verify('goal',job['id'])['ok'])

    def test_queue_rejects_external_writes_and_code_and_invalid_repeat(self):
        for agent,data in [('publish',{'service':'gmail','destination':'a@example.com','subject':'x','text':'x'}),('coder',{'request':'x'})]:
            with self.assertRaises(ValueError):self.bridge.team_schedule([{'id':'a','agent':agent,'input':data}],'x',0,300)
        with self.assertRaises(ValueError):self.bridge.team_schedule([{'id':'a','agent':'verify','input':{}}],'x',0,1)

    def test_new_task_has_specialists_before_execution(self):
        with patch.object(task_agents,'_run_pending',side_effect=lambda owner,job,emit:job):
            job=task_agents.execute('alice',[{'id':'a','agent':'writer','input':{'instruction':'x'}}],'Mağaza satış raporu')
        self.assertEqual(job['tasks'][0]['specialist']['id'],'store')
        self.assertEqual(task_agents._load('alice',job['id'])['tasks'][0]['specialist']['id'],'store')

    def test_save_failure_does_not_mutate_previous_team(self):
        entries=team.members('alice');team.save_members('alice',entries)
        changed=copy.deepcopy(entries);changed[0]['name']='Yeni ad'
        with patch.object(team.release_guard,'atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):team.save_members('alice',changed)
        self.assertEqual(team.members('alice'),entries)


if __name__=='__main__':unittest.main()
