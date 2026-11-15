"""Live canonical Scheduler/Core contracts for the three existing effect adapters.

Mock only model/external provider/developer boundaries. Real durable plan,
approval, resource lease, effect journal, WorkerResult CAS and output
projection run under isolated owner and native file/Outbox stores.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import (
    canonical_goal_control, canonical_goal_flow, canonical_restart_audit,
    canonical_scheduler_dispatch, goal_executor, goal_state_store,
    model_wait, nxapi, outbox, publish_services, resource_leases,
    scheduler_resource_gate, service_store, task_agents, task_results,
    untrusted_flow,
)


class CanonicalEffectfulSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.owner = 'alice'
        self.root = Path(self.temp.name)
        for target, attribute, value in (
            (goal_executor, 'STORE', self.root / 'goals'),
            (goal_executor, '_RESOURCE_LEASES', resource_leases.LeaseTable()),
            (scheduler_resource_gate, '_ACCOUNT_CLAIM_ROOT', self.root / 'claims'),
            (service_store, 'ROOT', self.root / 'services'),
            (nxapi, 'FILES_DIR', self.root / 'files'),
            (untrusted_flow, 'observe', lambda *_args, **_kwargs: None),
        ):
            self.stack.enter_context(patch.object(target, attribute, value))

    def create(self, task, request):
        return self.create_plan([task], request)

    def create_plan(self, tasks, request):
        rid = 'effect-' + uuid.uuid4().hex[:20]
        with patch.object(model_wait, 'ask', return_value=json.dumps({'tasks':tasks})):
            ident, _reply = canonical_goal_flow.try_create(self.owner, rid, request)
        self.assertIsInstance(ident, str)
        self.assertEqual(len(ident), 16)
        return ident

    def snapshots(self, ident):
        root = goal_executor._owner_root(self.owner)
        from modules import execution_record, goal_job_control
        with goal_job_control.locked(root, ident):
            return (
                goal_state_store.load(root / (ident + '.goalstate.json')),
                execution_record.load(root, self.owner, ident),
            )

    def offer(self, ident):
        options = canonical_scheduler_dispatch.discover(self.owner, max_offers=5)
        matches = [offer for offer in options if offer.selection.job_id == ident]
        self.assertEqual(len(matches), 1, options)
        return matches[0]

    def approve(self, ident):
        shown = goal_executor.read_job(self.owner, ident)
        self.assertEqual(shown['steps'][0]['state'], 'approval')
        key = goal_executor.control_key(shown)
        result = canonical_goal_control.approve_effect(
            self.owner, ident, expected_control=key,
        )
        self.assertIn('Scheduler', result)
        with self.assertRaises(PermissionError):
            canonical_goal_control.approve_effect(
                self.owner, ident, expected_control=key,
            )

    def test_writer_native_file_and_core_worker_result(self):
        ident = self.create({
            'id':'report', 'agent':'writer', 'depends':[],
            'input':{'instruction':'Kısa Markdown raporu yaz','filename':'report.md'},
        }, 'Kısa Markdown raporunu dosyaya kaydet.')
        with patch.object(model_wait, 'ask', return_value='# Doğrulanmış rapor\n\nİçerik'):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), self.offer(ident),
            ))
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'][0]['status'], 'succeeded')
        self.assertEqual(state['evidence'][0]['capability_id'], 'task.writer')
        self.assertEqual(state['evidence'][0]['command_id'], 'report:1:p1')
        output=record['outputs']['report']
        self.assertTrue(task_results.verify(output,owner=self.owner))
        self.assertTrue(Path(output['file']).is_file())
        self.assertEqual(output['sha256'],task_results.file_digest(output['file']))
        self.assertEqual(record['steps'][0]['attempts'],1)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())

    def test_coder_approval_then_verified_draft_first_attempt(self):
        ident = self.create({
            'id':'code', 'agent':'coder', 'depends':[],
            'input':{'request':'Bir Python taslağı oluştur'},
        }, 'Python kod taslağı ve testleri oluştur.')
        with patch('modules.developer.handle',side_effect=AssertionError('No code before consent')):
            self.assertFalse(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner),self.offer(ident),
            ))
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'],[])
        self.assertEqual(record['steps'][0]['state'],'approval')
        self.assertEqual(record['steps'][0]['attempts'],0)
        self.assertIn('approval_pending',
                      [item.status for item in canonical_restart_audit.inspect(
                          self.owner,ident).nodes])
        self.approve(ident)
        src=self.root/'draft.py'
        log=self.root/'tests.log'
        src.write_text('print(1)',encoding='utf-8')
        log.write_text('PASS',encoding='utf-8')
        source_hash=task_results.file_digest(src)
        log_hash=task_results.file_digest(log)
        sealed=task_results.seal('coder',{
            'state':'done','text':'Taslak testleri geçti','draft':True,
            'test_ok':True,'owner':self.owner,'file':str(src),
            'files':[{'file':str(src),'sha256':source_hash}],
            'test_log':str(log),'test_log_sha256':log_hash,
            'receipt':{'service':'coder_draft','remote_id':log_hash},
        })
        with patch('modules.developer.status',return_value={'enabled':True,'unlocked':True}),\
             patch.object(task_agents,'worker',return_value=sealed) as native:
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner),self.offer(ident),
            ))
        native.assert_called_once()
        state, record=self.snapshots(ident)
        self.assertEqual(state['evidence'][0]['capability_id'],'task.coder')
        self.assertEqual(state['evidence'][0]['status'],'succeeded')
        self.assertTrue(task_results.verify(record['outputs']['code'],owner=self.owner))
        self.assertEqual(record['steps'][0]['attempts'],1)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())

    def test_publish_requires_approval_and_outbox_sends_once(self):
        address='person@example.com'
        ident=self.create({
            'id':'send','agent':'publish','depends':[],
            'input':{'service':'gmail','destination':address,
                     'subject':'Merhaba','text':'Kısa mesaj'},
        }, 'person@example.com adresine kısa mesaj gönder.')
        receipt={'scope':'provider_accepted','service':'gmail',
                 'destination':address,'remote_id':'message-123'}
        with patch.object(outbox,'_permission_decision',return_value=('ask','Consent required')),\
             patch.object(publish_services,'send',return_value=receipt) as sender:
            self.assertFalse(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner),self.offer(ident),
            ))
            sender.assert_not_called()
            state, record=self.snapshots(ident)
            self.assertFalse(state['evidence'])
            self.assertEqual(record['steps'][0]['state'],'approval')
            self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())
            self.approve(ident)
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner),self.offer(ident),
            ))
            state, record=self.snapshots(ident)
            output=record['outputs']['send']
            self.assertTrue(task_results.verify(output,owner=self.owner))
            self.assertEqual(state['evidence'][0]['capability_id'],'task.publish')
            self.assertEqual(state['evidence'][0]['status'],'succeeded')
            self.assertEqual(outbox.get(self.owner,output['id'])['state'],'accepted')
            self.assertEqual(outbox.dispatch(self.owner,output['id'],approve=True)['state'],'done')
            self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())
            sender.assert_called_once()


    def test_publish_never_resends_after_core_acceptance_and_projection_crash(self):
        """Accepted provider result without ExecutionRecord projection is NOT retryable."""
        destination='person@example.com'
        ident=self.create({
            'id':'send','agent':'publish','depends':[],
            'input':{'service':'gmail','destination':destination,
                     'subject':'One', 'text':'one message'},
        },'person@example.com adresine bir mesaj gönder.')
        receipt={'scope':'provider_accepted','service':'gmail',
                 'destination':destination,'remote_id':'one-remote-id'}
        with patch.object(outbox,'_permission_decision',return_value=('ask','consent')),\
             patch.object(publish_services,'send',return_value=receipt) as sender:
            self.assertFalse(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner),self.offer(ident),
            ))
            self.approve(ident)
            with patch('modules.canonical_output_projection.project_accepted',
                       side_effect=OSError('simulated crash after Core CAS')):
                with self.assertRaises(OSError):
                    canonical_scheduler_dispatch.execute_offer(
                        SimpleNamespace(slug=self.owner),self.offer(ident),
                    )
            state, journal=self.snapshots(ident)
            self.assertEqual(len(state['evidence']),1)
            self.assertEqual(state['evidence'][0]['status'],'succeeded')
            self.assertNotIn('send',journal['outputs'])
            self.assertEqual(
                canonical_restart_audit.inspect(self.owner,ident).nodes[0].status,
                'accepted_unprojected',
            )
            self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())
            # Provider accepted message, persisted Outbox state remains
            # immutable. New approval/worker attempts cannot send again.
            sender.assert_called_once()
            from modules import effect_recovery_runtime
            self.assertIsNone(effect_recovery_runtime.reconcile(
                {
                    'owner':self.owner,'job_id':ident,'step_id':'send',
                    'command_id':'send:1:p1','attempt':1,
                    'expected_job_version':state['evidence'][0]['expected_job_version'],
                    'capability_id':'task.publish','capability_version':'1',
                    'input_digest':state['evidence'][0]['input_digest'],
                    'plan_version':1,'node_digest':state['evidence'][0]['node_digest'],
                },
                lambda: (_ for _ in ()).throw(AssertionError('No second send')),
                receipt_readback=True,
            ))
            sender.assert_called_once()

    def test_publish_writer_dependency_approved_source_tamper_blocks_send(self):
        """A previously approved draft must not authorize different file bytes."""
        destination='person@example.com'
        ident=self.create_plan([
            {'id':'draft','agent':'writer','depends':[],
             'input':{'instruction':'Write draft','filename':'draft.md'}},
            {'id':'send','agent':'publish','depends':['draft'],
             'input':{'service':'gmail','destination':destination,
                      'subject':'Draft','text_from_task':'draft'}},
        ], 'Raporu dosyaya kaydet, sonra person@example.com adresine gönder.')
        with patch.object(model_wait,'ask',return_value='**Immutable draft**'):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner),self.offer(ident),
            ))
        state, journal=self.snapshots(ident)
        self.assertTrue(task_results.verify(journal['outputs']['draft'],owner=self.owner))
        self.assertFalse(canonical_scheduler_dispatch.execute_offer(
            SimpleNamespace(slug=self.owner),self.offer(ident),
        ))
        self.approve(ident)
        path=Path(journal['outputs']['draft']['file'])
        path.write_text('changed after approval',encoding='utf-8')
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())
        with patch.object(publish_services,'send',
                          side_effect=AssertionError('Never send changed source')) as sender:
            sender.assert_not_called()
            self.assertEqual(canonical_scheduler_dispatch.discover(self.owner),())
