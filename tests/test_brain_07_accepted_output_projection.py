"""BRAIN-07 accepted canonical output -> existing ExecutionRecord.

All writes target temporary on-disk GoalState and ExecutionRecord. Provider
workers and UI are never invoked. Result envelopes use real Core CAS.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import release_guard
from modules import (
    canonical_output_projection, core_state_reducer, dependency_evidence,
    execution_record, goal_executor, goal_state, goal_state_store, goal_tools,
    runtime_worker_result, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url':'https://example.test/article','question':'read source'}


def node(name, deps=()):
    return {'id':name,'depends_on':list(deps),
            'capability_id':'task.research','input':dict(DATA),
            'expected_output':'verified source','acceptance':'domain proof'}


class AcceptedOutputProjectionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.owner_root=self.root/OWNER
        self.owner_root.mkdir(parents=True)
        self.path=self.owner_root/(JOB+'.goalstate.json')
        self.record=execution_record.path_for(self.owner_root,JOB)
        self.plan={'plan_version':1,'nodes':[
            node('left'), node('right'), node('child', ('left','right')),
        ]}
        initial=goal_state.new(owner=OWNER,job_id=JOB,
                               goal='Compare sources',authority='canonical')
        planned=core_state_reducer.apply(initial,{
            'op':'set_goal_plan','plan':self.plan,
            'reason_code':'TEST_PLAN','expected_version':initial['version'],
        })
        goal_state_store.create(self.path,planned)
        self.job={'id':JOB,'owner':OWNER,'request':'Compare sources',
                  'state':'running','goals':[],
                  'steps':[{'id':n['id'],
                            'tool':'research','input':copy.deepcopy(DATA),
                            'depends':list(n['depends_on']),'state':'queued'}
                           for n in self.plan['nodes']],
                  'outputs':{}}
        release_guard.atomic(self.record,execution_record.encode(self.job))
        p=patch.object(goal_executor,'STORE',self.root)
        p.start();self.addCleanup(p.stop)

    def proof(self,step,text=None):
        output={'state':'done','text':text or ('read '+step),
                'verification':{'fixture':step}}
        identity={'version':1,'owner':OWNER,'job_id':JOB,
                  'task_id':step,'attempt':1,'request':'Compare sources'}
        enriched,expected=runtime_worker_result.prepare(
            identity,'research',dict(DATA),
        )
        envelope=worker_result_hook.wrap_output(output,enriched)
        runtime_worker_result.accept_and_commit(envelope,expected)
        return output

    def persisted(self):
        return execution_record.load(self.owner_root,OWNER,JOB)

    def test_exact_accepted_output_projects_once(self):
        output=self.proof('left')
        self.assertTrue(canonical_output_projection.project_accepted(
            OWNER,JOB,'left',output,
        ))
        before=self.record.read_bytes()
        self.assertFalse(canonical_output_projection.project_accepted(
            OWNER,JOB,'left',output,
        ))
        self.assertEqual(self.record.read_bytes(),before)
        self.assertEqual(self.persisted()['steps'][0]['state'],'done')
        self.assertEqual(self.persisted()['outputs']['left'],output)
        self.assertEqual(len(goal_state_store.load(self.path)['evidence']),1)

    def test_unaccepted_worker_output_never_reaches_record(self):
        before=self.record.read_bytes()
        with self.assertRaises(canonical_output_projection.ProjectionFenceError):
            canonical_output_projection.project_accepted(
                OWNER,JOB,'left',{'state':'done','text':'unverified'},
            )
        self.assertEqual(self.record.read_bytes(),before)

    def test_mutated_output_after_worker_cas_is_rejected(self):
        output=self.proof('left')
        before=self.record.read_bytes()
        output['text']='changed after CAS'
        with self.assertRaisesRegex(
            canonical_output_projection.ProjectionFenceError,'differ',
        ):
            canonical_output_projection.project_accepted(OWNER,JOB,'left',output)
        self.assertEqual(self.record.read_bytes(),before)

    def test_foreign_owner_or_step_never_projects(self):
        output=self.proof('left')
        with self.assertRaises((PermissionError, ValueError)):
            canonical_output_projection.project_accepted('bob',JOB,'left',output)
        with self.assertRaises(canonical_output_projection.ProjectionFenceError):
            canonical_output_projection.project_accepted(OWNER,JOB,'missing',output)
        self.assertEqual(self.persisted()['outputs'],{})

    def test_changed_execution_step_never_projects(self):
        output=self.proof('left')
        tampered=self.persisted()
        tampered['steps'][0]['input']['url']='https://bad.test'
        release_guard.atomic(self.record,execution_record.encode(tampered))
        before=self.record.read_bytes()
        with self.assertRaisesRegex(
            canonical_output_projection.ProjectionFenceError,'differs',
        ):
            canonical_output_projection.project_accepted(OWNER,JOB,'left',output)
        self.assertEqual(self.record.read_bytes(),before)

    def test_user_revision_after_acceptance_does_not_project(self):
        output=self.proof('left')
        before=goal_state_store.load(self.path)
        updated=core_state_reducer.apply(before,{
            'op':'mutate_goal_intent','operation':'revise',
            'text':'new source list','priority':None,
            'reason_code':'USER_CORRECTION',
            'expected_version':before['version'],
        })
        goal_state_store.compare_and_swap(
            self.path,expected_version=before['version'],next_state=updated,
        )
        with self.assertRaisesRegex(
            canonical_output_projection.ProjectionFenceError,'changed',
        ):
            canonical_output_projection.project_accepted(OWNER,JOB,'left',output)
        self.assertEqual(self.persisted()['outputs'],{})

    def test_two_accepted_roots_project_independently(self):
        first=self.proof('left')
        second=self.proof('right')
        self.assertTrue(canonical_output_projection.project_accepted(
            OWNER,JOB,'right',second,
        ))
        self.assertTrue(canonical_output_projection.project_accepted(
            OWNER,JOB,'left',first,
        ))
        outputs=self.persisted()['outputs']
        self.assertEqual(set(outputs),{'left','right'})
        self.assertEqual(goal_state_store.load(self.path)['version'],3)
        self.assertEqual(len(goal_state_store.load(self.path)['evidence']),2)
        with patch.object(goal_tools,'verify',return_value=True):
            verified=dependency_evidence.require_persisted_research_dependencies(
                {'version':1,'owner':OWNER,'job_id':JOB,
                 'task_id':'child','attempt':1}, self.plan['nodes'][2],
            )
        self.assertEqual(set(verified),{'left','right'})

    def test_legacy_authority_never_projects(self):
        output=self.proof('left')
        original=goal_state_store.load(self.path)
        original['authority']='legacy'
        release_guard.atomic(
            self.path,__import__('json').dumps(original).encode('utf-8'),
        )
        with self.assertRaisesRegex(
            canonical_output_projection.ProjectionFenceError,'canonical',
        ):
            canonical_output_projection.project_accepted(OWNER,JOB,'left',output)


if __name__ == '__main__':
    unittest.main()
