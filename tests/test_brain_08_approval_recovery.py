"""BRAIN-08 real Core/SQLite/EffectJournal; only provider/native effects fake."""
import copy
import json
import threading
import time
import subprocess
import sys
import os
from pathlib import Path
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from unittest.mock import Mock, patch

import test_engine_modular  # noqa: F401
import test_goal_executor as goal_fixture
import test_service_work as service_fixture
from modules import (brain_batch_checkpoint, effect_recovery_runtime, goal_approval,
                     goal_executor as goals, goal_tools, llm, outbox, service_store,
                     scheduler_resource_gate, resource_leases)


class GoalApprovalTests(unittest.TestCase):
    def setUp(self):
        self.c=goal_fixture.GoalTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.bridge=Mock();self.c.profile.data['items']=[{'id':7,'text':'selected note'},{'id':9,'text':'other'}]
        native=patch.object(goal_tools.app_actions,'_owned',return_value=nullcontext(self.bridge))
        native.start();self.addCleanup(native.stop)

    def prepare(self):
        self.c.responses(self.c.plan('Seçilen notu sil'),self.c.tool('action',{'action':'note_delete','params':{'nid':7}}))
        goals.run(self.c.runtime,'7 kimlikli notu sil')
        job=goals.latest('alice');self.assertEqual(job['state'],'approval')
        self.bridge.note_delete.assert_not_called()
        return job

    def test_real_goal_approval_is_bound_consumed_and_never_replayed(self):
        job=self.prepare();certificate=job['steps'][0]['approval']
        self.assertEqual(certificate['binding']['job_id'],job['id'])
        self.assertEqual(certificate['binding']['task_id'],'s1')
        self.assertEqual(certificate['binding']['operation'],'action')
        self.c.responses(self.c.done('s1'),self.c.finish())
        goals.handle(self.c.runtime,'hedef onayla')
        saved=goals.latest('alice');self.assertIsNotNone(saved['steps'][0]['approval']['consumed_at'])
        goals.handle(self.c.runtime,'hedef onayla')
        self.bridge.note_delete.assert_called_once_with(nid=7)

    def test_changed_input_or_other_plan_step_revokes_approval(self):
        for change in ('target','plan'):
            with self.subTest(change=change):
                job=self.prepare()
                if change=='target':job['steps'][0]['input']['params']['nid']=9
                else:job['steps'].append({'id':'s2','goal':0,'tool':'research','input':{'url':'https://example.test'},'depends':[],'state':'queued'})
                goals._save(job)
                goals.handle(self.c.runtime,'hedef onayla')
                self.assertEqual(goals.latest('alice')['state'],'review')
                self.bridge.note_delete.assert_not_called()
                # Finish this fixture's job before the next independent case.
                goals.cancel_job('alice',job['id'])

    def test_expired_approval_does_not_execute(self):
        job=self.prepare()
        with patch.object(goal_approval.time,'time',return_value=job['approval_at']+121):
            goals.handle(self.c.runtime,'hedef onayla')
        self.assertEqual(goals.latest('alice')['state'],'review')
        self.bridge.note_delete.assert_not_called()

    def test_same_local_record_id_with_changed_content_invalidates_approval(self):
        self.prepare()
        self.c.profile.data['items'][0]['text']='changed after preview'
        goals.handle(self.c.runtime,'hedef onayla')
        self.assertEqual(goals.latest('alice')['state'],'review')
        self.bridge.note_delete.assert_not_called()

    def test_two_pending_goals_require_explicit_job_and_snapshot(self):
        first=self.prepare();second=copy.deepcopy(first);second['id']=uuid.uuid4().hex[:16]
        for key in ('_canonical_version','_execution_snapshot','_goal_version_fence'):second.pop(key,None)
        goals._save(second)
        second['steps'][0]['approval']=goal_approval.prepare(second,second['steps'][0],second['outputs']['s1'],self.c.profile)
        goals._save(second)
        self.assertIn('Birden fazla',goals.handle(self.c.runtime,'hedef onayla'))
        self.bridge.note_delete.assert_not_called()
        self.c.responses(self.c.done('s1'),self.c.finish())
        command='hedef onayla '+first['id']+' '+goals.control_key(goals.read_job('alice',first['id']))
        goals.handle(self.c.runtime,command)
        self.bridge.note_delete.assert_called_once_with(nid=7)
        self.assertEqual(goals.read_job('alice',second['id'])['state'],'approval')

    def test_atomic_consume_race_and_failed_save_never_authorize_two_effects(self):
        job=self.prepare()
        with patch.object(goals,'_save',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):goal_approval.consume(job,job['steps'][0],job['outputs']['s1'],profile=self.c.profile)
        self.assertIsNone(goals.read_job('alice',job['id'])['steps'][0]['approval']['consumed_at'])
        barrier=threading.Barrier(2)
        def consume(_):
            current=goals.read_job('alice',job['id']);barrier.wait(5)
            try:
                goal_approval.consume(current,current['steps'][0],current['outputs']['s1'],profile=self.c.profile);return 'consumed'
            except (ValueError,PermissionError):return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(consume,range(2)))
        self.assertEqual(results.count('consumed'),1)
        self.assertEqual(results.count('rejected'),1)
        # Restart sees consumed approval but no effect; conservative review, no replay.
        goals.handle(self.c.runtime,'hedef onayla')
        self.bridge.note_delete.assert_not_called()
        self.assertEqual(goals.latest('alice')['state'],'review')

    def test_two_processes_cannot_consume_the_same_approval(self):
        job=self.prepare()
        script=r'''
import sys,time
from pathlib import Path
from types import SimpleNamespace
import json
import test_engine_modular
from modules import goal_executor as goals, goal_approval
goals.STORE=Path(sys.argv[1]);job=goals.read_job('alice',sys.argv[2])
ready=Path(sys.argv[3]);ready.write_text('ready')
deadline=time.monotonic()+30
while not Path(sys.argv[4]).exists():
    if time.monotonic()>deadline:raise RuntimeError('barrier deadline')
    time.sleep(.01)
try:
    goal_approval.consume(job,job['steps'][0],job['outputs']['s1'],profile=SimpleNamespace(slug='alice',data=json.loads(sys.argv[5])));print('CONSUMED')
except (ValueError,PermissionError):print('REJECTED')
'''
        marker=self.c.root/'go';children=[]
        def cleanup():
            for process in children:
                if process.poll() is None:process.kill()
                process.wait(10)
                if process.stdout:process.stdout.close()
        self.addCleanup(cleanup)
        ready=[self.c.root/f'ready{i}' for i in range(2)]
        environment=dict(os.environ)
        environment['PYTHONPATH']=os.pathsep.join((str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)))
        for path in ready:
            children.append(subprocess.Popen([sys.executable,'-c',script,str(goals.STORE),job['id'],str(path),str(marker),json.dumps(self.c.profile.data)],
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=environment))
        deadline=time.monotonic()+30
        while not all(path.exists() for path in ready):
            for process in children:
                if process.poll() is not None:
                    self.fail('Approval child exited before barrier: '+process.communicate(timeout=2)[0][-3000:])
            self.assertLess(time.monotonic(),deadline,repr([(p.poll(),ready[i].exists()) for i,p in enumerate(children)]))
            time.sleep(.01)
        marker.write_text('go')
        outputs=[process.communicate(timeout=15)[0] for process in children]
        self.assertEqual(sum('CONSUMED' in output for output in outputs),1,outputs)
        self.assertEqual(sum('REJECTED' in output for output in outputs),1,outputs)
        self.assertTrue(all(process.returncode==0 for process in children),outputs)


class _OutboxFixture:
    def setUp(self):
        self.c=service_fixture.WorkTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.payload=self.c.payload;self.receipt=self.c.receipt
        from modules import publish_services
        data=patch.object(publish_services,'DATA_DIR',__import__('pathlib').Path(self.c.tmp.name)/'connections')
        data.start();self.addCleanup(data.stop)
        self.transport=patch('modules.publish_services.send',return_value=self.receipt)
        self.send=self.transport.start();self.addCleanup(self.transport.stop)
        # Keep the real process claim with a fixture-local Path.
        root=patch.object(scheduler_resource_gate,'_ACCOUNT_CLAIM_ROOT',__import__('pathlib').Path(self.c.tmp.name)/'provider')
        root.start();self.addCleanup(root.stop)


class OutboxRecoveryTests(_OutboxFixture, unittest.TestCase):
    def test_account_connection_change_revokes_pending_approval_before_consume(self):
        from modules import publish_services as services
        path=services.DATA_DIR/'google_users'/'alice'/'google_gmail_write_token.json'
        path.parent.mkdir(parents=True)
        account={'client_id':'client','client_secret':'secret','refresh_token':'first','token':'old'}
        path.write_text(json.dumps(account))
        oid=outbox.prepare('alice',self.payload,'one')
        path.write_text(json.dumps(dict(account,refresh_token='changed')))
        self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'blocked')
        self.assertFalse(outbox.get('alice',oid)['approval_consumed'])
        self.send.assert_not_called()

    def test_actual_google_client_checks_connection_but_allows_access_token_refresh(self):
        from types import SimpleNamespace
        from modules import publish_services as services,google_api
        account={'client_id':'client','client_secret':'secret','refresh_token':'first','token':'old'}
        path=services.DATA_DIR/'google_users'/'alice'/'google_gmail_write_token.json'
        path.parent.mkdir(parents=True);path.write_text(json.dumps(account))
        expected=services.connection_digest('alice',self.payload)
        credentials=SimpleNamespace(to_json=lambda:json.dumps(dict(account,token='refreshed')))
        with patch.object(google_api,'_creds',return_value=credentials), \
             patch('httplib2.Http',return_value='bounded-http') as http, \
             patch('google_auth_httplib2.AuthorizedHttp',return_value='authorized-http') as authorized, \
             patch('googleapiclient.discovery.build') as build, \
             services.approved_connection('alice',self.payload,expected):
            services.google_service('gmail')
            http.assert_called_once_with(timeout=google_api._SERVICE_HTTP_TIMEOUT_SECONDS)
            authorized.assert_called_once_with(credentials,http='bounded-http')
            self.assertEqual(build.call_args.kwargs['http'],'authorized-http')
            credentials.to_json=lambda:json.dumps(dict(account,refresh_token='other-account'))
            with self.assertRaises(PermissionError):services.google_service('gmail')
            self.assertEqual(build.call_count,1)

    def test_expiry_and_unknown_never_send_again(self):
        oid=outbox.prepare('alice',self.payload,'one')
        with patch.object(outbox.time,'time',return_value=time.time()+121):
            self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'blocked')
        self.send.assert_not_called()
        self.send.side_effect=TimeoutError('provider response lost')
        self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'failed')
        self.assertTrue(outbox.get('alice',oid)['approval_consumed'])
        self.assertEqual(outbox.recover('alice','one')['state'],'failed')
        outbox.dispatch('alice',oid,approve=True)
        self.send.assert_called_once()

    def test_wrong_target_receipt_stays_unknown(self):
        self.send.return_value={**self.receipt,'destination':'other@example.test'}
        oid=outbox.prepare('alice',self.payload,'one')
        self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'failed')
        self.assertEqual(outbox.get('alice',oid)['state'],'unknown')
        self.assertEqual(outbox.recover('alice','one')['state'],'failed')
        self.send.assert_called_once()

    def test_restart_after_receipt_before_final_state_recovers_without_provider(self):
        oid=outbox.prepare('alice',self.payload,'one')
        with service_store.database('alice') as db:
            db.execute("UPDATE outbox SET state='sending',receipt=? WHERE id=?",(service_store.encode(self.receipt),oid))
        self.assertEqual(outbox.recover('alice','one')['state'],'done')
        self.assertEqual(outbox.get('alice',oid)['state'],'accepted')
        self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'done')
        self.send.assert_not_called()

    def test_live_provider_claim_rejects_before_consuming_approval(self):
        oid=outbox.prepare('alice',self.payload,'one')
        with scheduler_resource_gate.provider_resource_claim('gmail'):
            self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'blocked')
        self.assertFalse(outbox.get('alice',oid)['approval_consumed'])
        self.send.assert_not_called()
        self.assertEqual(outbox.dispatch('alice',oid,approve=True)['state'],'done')
        self.send.assert_called_once()


class BatchCheckpointTests(_OutboxFixture, unittest.TestCase):
    def test_real_typed_batch_repeated_request_never_repeats_domain_writes(self):
        import test_brain_03_observation_parity as fixture
        from test_brain_primary_understanding import action,envelope
        from modules import brain_entry
        c=fixture.ObservationParityTests();c.setUp();self.addCleanup(c.doCleanups)
        actions=[]
        for ident,text in (('a1','A notu'),('a2','B notu')):
            row=action(capability_id='notes.add',arguments={'text':text},action_id=ident)
            row['argument_sources']={'text':text};actions.append(row)
        command='A notu ve B notu ekle'
        entry,result,feedback,_=c.model_turn(command,raw=envelope(operation='action_batch',confidence='HIGH',actions=actions))
        self.assertEqual(feedback.result_status,'handled')
        before=copy.deepcopy(c.ctx.profile.data['items'])
        raw_handler=Mock(side_effect=AssertionError('raw parser fallback'))
        output,replayed,_=brain_entry.handoff(c.ctx,entry,raw_handler,command)
        self.assertEqual(replayed.reason_code,'CORE_BATCH_CHECKPOINT_REPLAY_BLOCKED')
        self.assertEqual(c.ctx.profile.data['items'],before)
        self.assertIn('tekrar yürütülmedi',output)
        raw_handler.assert_not_called()

    def test_partial_and_interrupted_batch_survive_restart_without_replay(self):
        actions=({'action_id':'a1','arguments':{'text':'one'}},{'action_id':'a2','depends_on':['a1']})
        self.assertIsNone(brain_batch_checkpoint.begin('alice','r1',actions))
        brain_batch_checkpoint.record('alice','r1','a1','running')
        brain_batch_checkpoint.record('alice','r1','a1','succeeded','persisted note')
        brain_batch_checkpoint.record('alice','r1','a2','running')
        restarted=brain_batch_checkpoint.begin('alice','r1',actions)
        self.assertEqual(restarted['actions'],{'a1':'succeeded','a2':'running'})
        self.assertIn('a2: unknown',brain_batch_checkpoint.replay_text(restarted))
        with self.assertRaises(ValueError):brain_batch_checkpoint.record('alice','r1','a1','running')
        with self.assertRaises(ValueError):brain_batch_checkpoint.begin('alice','r1',({'action_id':'changed'},))
        self.send.assert_not_called()


class EffectReplayTests(_OutboxFixture, unittest.TestCase):
    def effect_with_local_receipt(self, phase):
        from types import SimpleNamespace
        from pathlib import Path
        from modules import goal_state,goal_state_store,core_state_reducer,runtime_worker_result,task_results
        root=patch.object(goals,'STORE',Path(self.c.tmp.name)/'goals');root.start();self.addCleanup(root.stop)
        ident=uuid.uuid4().hex[:16];payload=dict(self.payload,text=phase)
        step={'id':'send','tool':'publish','input':payload,'attempts':1,'depends':[],'state':'running'}
        job={'id':ident,'owner':'alice','request':'send exact message','outputs':{}}
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        path=goals._root('alice')/(ident+'.goalstate.json')
        initial=goal_state.new(owner='alice',job_id=ident,goal=job['request'],execution_mode='durable')
        goal_state_store.create(path,initial)
        _identity,expected=runtime_worker_result.prepare(goals._identity(job,step),'publish',payload,expected_job_version=0)
        effect_recovery_runtime.record_intent(expected)
        oid=outbox.prepare('alice',payload,ident+':send')
        output=task_results.seal('publish',outbox.dispatch('alice',oid,approve=True))
        if phase!='intent_only':effect_recovery_runtime.record_receipt(expected,output)
        # A genuine lifecycle CAS across restart must not lose the old intent.
        running=core_state_reducer.apply(initial,{'op':'set_state','state':'running',
            'expected_version':0,'reason_code':'USER_GOAL_RESUMED'})
        goal_state_store.compare_and_swap(path,expected_version=0,next_state=running)
        return runtime,job,step,path,oid

    def test_actual_goal_recovery_fills_receipt_to_core_gap_without_resending(self):
        from modules import goal_state_store
        for phase in ('intent_only','receipt_before_core'):
            with self.subTest(phase=phase):
                runtime,job,step,path,_=self.effect_with_local_receipt(phase)
                before=self.send.call_count
                recovered=goals._reconcile(runtime,job,step)
                self.assertEqual(recovered['state'],'done')
                accepted=goal_state_store.load(path)
                self.assertEqual(accepted['state'],'running')  # Receipt is not global completion.
                self.assertEqual(len(accepted['evidence']),1)
                self.assertEqual(accepted['evidence'][0]['command_id'],'send:1')
                self.assertIsNone(goals._reconcile(runtime,job,step))
                self.assertEqual(goal_state_store.load(path)['version'],accepted['version'])
                self.assertEqual(self.send.call_count,before)

    def test_conflicting_local_and_effect_receipt_cannot_be_accepted(self):
        from modules import effect_journal,goal_state_store
        runtime,job,step,path,oid=self.effect_with_local_receipt('receipt_before_core')
        with service_store.database('alice') as db:
            changed=dict(self.receipt,remote_id='different-provider-receipt')
            db.execute('UPDATE outbox SET receipt=? WHERE id=?',(service_store.encode(changed),oid))
        with self.assertRaises(effect_journal.ContractViolation):goals._reconcile(runtime,job,step)
        self.assertFalse(goal_state_store.load(path)['evidence'])
        self.send.assert_called_once()

    def test_canonical_planned_effect_receipt_requires_exact_plan_fence(self):
        """Effect journal accepts a full planned fence, never a partial v1 downgrade.

        This only verifies write-ahead identity and recovery isolation. It
        does NOT authorize a writer/coder/publish Scheduler worker or effect.
        """
        import hashlib
        from pathlib import Path
        payload_digest = hashlib.sha256(b"immutable-canonical-payload").hexdigest()
        expected = {
            'owner': 'alice', 'job_id': '0123456789abcdef', 'step_id': 'send',
            'command_id': 'send:1:p1', 'attempt': 1,
            'expected_job_version': 2, 'capability_id': 'task.publish',
            'capability_version': '1', 'input_digest': payload_digest,
            'plan_version': 1, 'node_digest': 'a' * 64,
        }
        with patch.object(goals, 'STORE', Path(self.c.tmp.name) / 'planned_goals'):
            effect_recovery_runtime.record_intent(expected)
            self.assertEqual(effect_recovery_runtime.status(expected), 'unknown')
            with self.assertRaises(effect_recovery_runtime.EffectReplayBlocked):
                effect_recovery_runtime.record_intent(expected)
            # A newer Core version or changed canonical digest must not
            # adopt the old intent/receipt as if it belonged to this plan.
            for changed in (dict(expected, expected_job_version=3),
                            dict(expected, node_digest='b' * 64),
                            dict(expected, plan_version=2, command_id='send:1:p2')):
                self.assertEqual(effect_recovery_runtime.status(changed), 'not_started')
                with self.assertRaises(effect_recovery_runtime.EffectReplayBlocked):
                    effect_recovery_runtime.record_intent(changed)
            effect_recovery_runtime.record_receipt(
                expected, {'receipt': {'service': 'gmail', 'remote_id': 'receipt-1'}},
            )
            self.assertEqual(effect_recovery_runtime.status(expected), 'succeeded')
            self.assertEqual(
                effect_recovery_runtime.status(dict(expected, node_digest='b' * 64)),
                'not_started',
            )
        self.send.assert_not_called()

    def test_malformed_planned_effect_fence_is_rejected(self):
        valid = {
            'owner': 'alice', 'job_id': '0123456789abcdef', 'step_id': 'send',
            'command_id': 'send:1:p1', 'attempt': 1,
            'expected_job_version': 2, 'capability_id': 'task.publish',
            'capability_version': '1', 'input_digest': 'c' * 64,
            'plan_version': 1, 'node_digest': 'd' * 64,
        }
        for invalid in (dict(valid, node_digest='nope'),
                        {k:v for k,v in valid.items() if k!='node_digest'},
                        dict(valid, untrusted='arbitrary'),
                        dict(valid, plan_version=True)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    effect_recovery_runtime._checked(invalid)

    def test_new_attempt_or_core_version_cannot_bypass_existing_intent(self):
        from modules import runtime_worker_result
        identity={'owner':'alice','job_id':'0123456789abcdef','task_id':'send','attempt':1}
        _identity,expected=runtime_worker_result.prepare(identity,'publish',self.payload,expected_job_version=0)
        with patch.object(goals,'STORE',__import__('pathlib').Path(self.c.tmp.name)/'goals'):
            effect_recovery_runtime.record_intent(expected)
            for replay in (expected,dict(expected,attempt=2,command_id='send:2'),dict(expected,expected_job_version=1)):
                with self.assertRaises(effect_recovery_runtime.EffectReplayBlocked):effect_recovery_runtime.record_intent(replay)
            self.assertEqual(effect_recovery_runtime.status(expected),'unknown')
            other=dict(expected,step_id='different',command_id='different:1')
            effect_recovery_runtime.record_intent(other)
        self.send.assert_not_called()
