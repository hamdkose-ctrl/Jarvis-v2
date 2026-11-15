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
        rid = 'effect-' + uuid.uuid4().hex[:20]
        with patch.object(model_wait, 'ask', return_value=json.dumps({'tasks':[task]})):
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
