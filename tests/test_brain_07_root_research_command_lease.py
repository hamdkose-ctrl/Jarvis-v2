"""BRAIN-07: real canonical independent research command ownership.

Real GoalState/WorkerResult persistence and OS locks. Synthetic provider
outputs only, with the existing DecisionAuthority and specialist boundary.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import (
    core_state_reducer, goal_executor, goal_state, goal_state_store,
    goal_tools, resource_leases, runtime_worker_result,
    scheduler_resource_gate, specialist_orchestrator, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url':'https://example.test/source','question':'compare sources'}


def identity(step):
    return {'version':1,'owner':OWNER,'job_id':JOB,'task_id':step,
            'attempt':1,'request':'compare sources'}


def node(name):
    return {'id':name,'depends_on':[],'capability_id':'task.research',
            'input':dict(DATA),'expected_output':'verified research',
            'acceptance':'source verified'}


class CanonicalResearchRootCommandTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.path=self.root/OWNER/(JOB+'.goalstate.json')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        created=goal_state.new(owner=OWNER,job_id=JOB,goal='Compare sources',
                               authority='canonical')
        plan=core_state_reducer.apply(created,{
            'op':'set_goal_plan','plan':{'plan_version':1,'nodes':[node('left'),node('right')]},
            'reason_code':'TEST_PLAN','expected_version':created['version'],
        })
        goal_state_store.create(self.path,plan)
        self.table=resource_leases.LeaseTable()
        for name,value in (('STORE',self.root),('_RESOURCE_LEASES',self.table)):
            patched=patch.object(goal_executor,name,value)
            patched.start()
            self.addCleanup(patched.stop)
        self.runtime=SimpleNamespace(profile=SimpleNamespace(slug=OWNER))
        self.job={'id':JOB,'owner':OWNER,'request':'compare sources',
                  'state':'running','outputs':{}}

    def prepared(self, step):
        return runtime_worker_result.prepare(identity(step),'research',dict(DATA))

    def wrapped(self, step, enriched):
        return worker_result_hook.wrap_output({
            'state':'done','text':step+' synthetic verified',
            'verification':{'fixture':step},
        },enriched)

    def test_duplicate_root_command_cannot_enter_real_worker(self):
        enriched,expected=self.prepared('left')
        other=resource_leases.LeaseTable()
        with scheduler_resource_gate.root_research_worker(
            self.table,enriched,expected,
        ):
            with self.assertRaises(resource_leases.LeaseConflict):
                with scheduler_resource_gate.root_research_worker(
                    other,enriched,expected,
                ):
                    self.fail('Duplicate root entered worker scope')
        self.assertEqual(self.table._commands,{})
        self.assertEqual(other._commands,{})

    def test_two_independent_roots_commit_after_one_root_advances_version(self):
        left,l_expected=self.prepared('left')
        right,r_expected=self.prepared('right')
        with scheduler_resource_gate.root_research_worker(
            self.table,left,l_expected,
        ) as commit_left, scheduler_resource_gate.root_research_worker(
            self.table,right,r_expected,
        ) as commit_right:
            self.assertEqual(len(self.table._holders),2)
            commit_left(self.wrapped('left',left))
            commit_right(self.wrapped('right',right))
        state=goal_state_store.load(self.path)
        self.assertEqual(state['version'],3)
        self.assertEqual({e['step_id'] for e in state['evidence']},{'left','right'})
        self.assertEqual(self.table._commands,{})

    def test_real_specialist_roots_overlap_and_both_commit(self):
        """Actual specialist threads overlap at the worker boundary.

        The provider itself is a synthetic barrier; persistent WorkerResult
        CAS, resource claims and admission are real.
        """
        started = threading.Barrier(2)
        entered = []
        mutex = threading.Lock()
        def synthetic_provider(_runtime, _kind, _data, _deps, execution, **_kwargs):
            started.wait(timeout=12)
            with mutex:
                entered.append(execution['task_id'])
            return {'state':'done','text':'verified '+execution['task_id'],
                    'verification':{'fixture':execution['task_id']}}

        def perform(name):
            step={'id':name,'tool':'research','input':dict(DATA),
                  'depends':[],'state':'running'}
            return specialist_orchestrator._execute_step(
                self.runtime, self.job, step, identity(name),
            )

        with (patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase':'execute'}),
              patch('modules.effect_recovery_runtime.required',return_value=False),
              patch('modules.research_evidence.news_requested',return_value=False),
              patch.object(goal_tools,'verify',return_value=True),
              patch.object(goal_tools,'execute',side_effect=synthetic_provider)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                left=pool.submit(perform,'left')
                right=pool.submit(perform,'right')
                self.assertEqual(left.result(timeout=20)['state'],'done')
                self.assertEqual(right.result(timeout=20)['state'],'done')
        self.assertEqual(set(entered),{'left','right'})
        canonical=goal_state_store.load(self.path)
        self.assertEqual({e['step_id'] for e in canonical['evidence']},
                         {'left','right'})
        self.assertEqual(canonical['version'],3)
        self.assertEqual(self.table._commands,{})

    def test_user_intent_edit_during_root_blocks_late_commit(self):
        enriched,expected=self.prepared('left')
        with scheduler_resource_gate.root_research_worker(
            self.table,enriched,expected,
        ) as commit:
            before=goal_state_store.load(self.path)
            edited=core_state_reducer.apply(before,{
                'op':'mutate_goal_intent','operation':'revise',
                'text':'now use different sources','priority':None,
                'reason_code':'USER_CORRECTION',
                'expected_version':before['version'],
            })
            goal_state_store.compare_and_swap(
                self.path,expected_version=before['version'],next_state=edited,
            )
            with self.assertRaises(scheduler_resource_gate.ReadOnlyAdmissionError):
                commit(self.wrapped('left',enriched))
        self.assertEqual(goal_state_store.load(self.path)['evidence'],[])

    def test_specialist_calls_root_guard_before_provider_and_commits_once(self):
        step={'id':'left','tool':'research','input':dict(DATA),
              'depends':[],'state':'running'}
        provider={'state':'done','text':'verified source',
                  'verification':{'fixture':'provider'}}
        with (patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase':'execute'}),
              patch('modules.effect_recovery_runtime.required',return_value=False),
              patch('modules.research_evidence.news_requested',return_value=False),
              patch.object(goal_tools,'verify',return_value=True),
              patch.object(goal_tools,'execute',return_value=provider) as worker):
            result=specialist_orchestrator._execute_step(
                self.runtime,self.job,step,identity('left'),
            )
        self.assertEqual(result,provider)
        worker.assert_called_once()
        self.assertEqual(len(goal_state_store.load(self.path)['evidence']),1)
        self.assertEqual(self.table._commands,{})

    def test_duplicate_specialist_entry_does_not_call_provider(self):
        enriched,expected=self.prepared('left')
        step={'id':'left','tool':'research','input':dict(DATA),
              'depends':[],'state':'running'}
        with (scheduler_resource_gate.root_research_worker(
                    resource_leases.LeaseTable(),enriched,expected),
              patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase':'execute'}),
              patch('modules.effect_recovery_runtime.required',return_value=False),
              patch('modules.research_evidence.news_requested',return_value=False),
              patch.object(goal_tools,'execute') as worker):
            with self.assertRaises(resource_leases.LeaseConflict):
                specialist_orchestrator._execute_step(
                    self.runtime,self.job,step,identity('left'),
                )
            worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
