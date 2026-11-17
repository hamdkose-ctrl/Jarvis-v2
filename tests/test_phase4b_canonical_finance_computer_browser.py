"""Phase 4B only: finance, computer and readonly browser through one Scheduler.

Use real GoalState, RID/attempt approval, ResourceLease and WorkerResult CAS.
Physical desktop/browser boundaries are mocked, not Core ownership.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_canonical_effectful_scheduler import CanonicalEffectfulSchedulerTests as _Harness
from modules import (
    canonical_goal_control, canonical_goal_flow, canonical_scheduler_dispatch,
    desktop_agent, goal_executor, task_plan_contracts, task_results, task_workers,
)


class CanonicalPhase4BTests(unittest.TestCase):
    setUp = _Harness.setUp
    create = _Harness.create
    create_plan = _Harness.create_plan
    snapshots = _Harness.snapshots
    offer = _Harness.offer

    def run_offer(self, ident):
        return canonical_scheduler_dispatch.execute_offer(
            SimpleNamespace(slug=self.owner), self.offer(ident),
        )

    def test_browser_plan_admission_requires_explicit_mode(self):
        self.assertIn('finance', task_plan_contracts.WORKER_CATALOG)
        self.assertIn('computer', task_plan_contracts.WORKER_CATALOG)
        self.assertIn('browser', task_plan_contracts.WORKER_CATALOG)
        for mode in (None, 'execute', ''):
            data = {'url':'https://example.org','instruction':'Click submit'}
            if mode is not None:
                data['mode'] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                canonical_goal_flow._canonical_plan([
                    {'id':'browse','agent':'browser','depends':[],'input':data}
                ],allow_effects=True)
        for mode in ('readonly', 'interactive'):
            with self.subTest(admitted=mode):
                plan = canonical_goal_flow._canonical_plan([
                    {'id':'browse','agent':'browser','depends':[],
                     'input':{'url':'https://example.org','instruction':'Use the form',
                              'mode':mode}}
                ], allow_effects=True)
                self.assertEqual(plan['nodes'][0]['capability_id'], 'task.browser')

    def test_finance_readonly_worker_result(self):
        ident = self.create({'id': 'money', 'agent': 'finance',
            'input': {'operation': 'portfolio_summary', 'payload':
                '[{"ticker":"THYAO","quantity":"2","price":"100","currency":"TRY"}]'}},
            'Summarize the portfolio figures I provided.')
        self.assertTrue(self.run_offer(ident))
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'][0]['capability_id'], 'task.finance')
        self.assertEqual(state['evidence'][0]['command_id'], 'money:1:p1')
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())
        self.assertTrue(task_results.verify(record['outputs']['money'], owner=self.owner))

    def test_computer_pilot_no_click_with_receipt(self):
        ident = self.create({'id': 'window', 'agent': 'computer',
            'input': {'app': 'calculator', 'operation': 'observe'}},
            'Observe my open calculator without clicking.')
        observation = {'window': {'title': 'Calculator'}, 'controls': [
            {'automation_id':'x','name':'0','type':'Text','bounds':[0,0,40,30]}]}
        with patch.object(desktop_agent, 'run', return_value={
                'state':'done', 'observation':observation}) as run:
            self.assertTrue(self.run_offer(ident))
        run.assert_called_once()
        self.assertTrue(run.call_args.kwargs['read_only'])
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'][0]['capability_id'], 'task.computer')
        self.assertEqual(state['evidence'][0]['command_id'], 'window:1:p1')
        self.assertTrue(task_results.verify(record['outputs']['window'], owner=self.owner))

    def test_finance_trade_and_computer_click_are_rejected_before_worker_admission(self):
        denied = (
            {'id':'trade','agent':'finance','depends':[],
             'input':{'operation':'execute_trade','payload':'{}'}},
            {'id':'click','agent':'computer','depends':[],
             'input':{'app':'calculator','operation':'click'}},
        )
        for task in denied:
            with self.subTest(agent=task['agent']), self.assertRaises(ValueError):
                canonical_goal_flow._canonical_plan([task], allow_effects=True)

    def test_browser_effect_capable_result_cannot_be_projected_as_readonly(self):
        ident = self.create({'id':'browse','agent':'browser','depends':[],
            'input':{'url':'https://example.org','instruction':'Read page',
                     'mode':'readonly'}}, 'Read the page without interacting.')
        self.assertFalse(self.run_offer(ident))
        shown = goal_executor.read_job(self.owner, ident)
        canonical_goal_control.approve_effect(
            self.owner, ident, expected_control=goal_executor.control_key(shown))
        screenshot = self.root / 'unexpected-browser-effect.png'
        screenshot.write_bytes(b'mocked-native-browser-image')
        non_readonly = {'state':'done', 'page':{'url':'https://example.org','title':'Example'},
                        'steps':[{'op':'goto','url':'https://example.org','verified':True},
                                 {'op':'read','url':'https://example.org','verified':True}],
                        'image':str(screenshot)}
        with patch.object(task_workers, 'run', return_value=non_readonly):
            with self.assertRaisesRegex(PermissionError, 'readonly'):
                self.run_offer(ident)
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'], [])
        self.assertEqual(record['steps'][0]['attempts'], 1)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())

    def test_browser_requires_consent_then_only_readonly_actions(self):
        ident = self.create({'id':'browse', 'agent':'browser', 'input':{
            'url':'https://example.org', 'instruction':'Read the page',
            'mode':'readonly'}}, 'Read example.org without clicking.')
        with patch.object(task_workers, 'run', side_effect=AssertionError(
                'No browser before exact user approval')):
            self.assertFalse(self.run_offer(ident))
        shown = goal_executor.read_job(self.owner, ident)
        self.assertEqual(shown['steps'][0]['state'], 'approval')
        canonical_goal_control.approve_effect(
            self.owner, ident, expected_control=goal_executor.control_key(shown),
        )
        readonly = {'state':'done', 'readonly':True, 'steps':[
            {'op':'goto','url':'https://example.org','verified':True},
            {'op':'read','url':'https://example.org','verified':True}],
            'page':{'url':'https://example.org','title':'Example'}}
        readonly['receipt'] = task_results.browser_readonly_receipt(readonly)
        with patch.object(task_workers, 'run', return_value=readonly) as run:
            self.assertTrue(self.run_offer(ident))
        run.assert_called_once()
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'][0]['capability_id'], 'task.browser')
        self.assertEqual(state['evidence'][0]['command_id'], 'browse:1:p1')
        self.assertTrue(task_results.verify(record['outputs']['browse'], owner=self.owner))
        unsafe = dict(readonly, steps=[{'op':'click','verified':True}])
        with self.assertRaises(ValueError):
            task_results.seal('browser', unsafe)


if __name__ == '__main__':
    unittest.main()
