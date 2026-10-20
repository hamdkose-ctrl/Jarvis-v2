"""Durable planning budgets; all models/tools are fake, source state is temporary."""
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from test_stale_goal_and_quota import _Base
from modules import goal_executor as goals, goal_tools, model_wait


class GoalTurnBudgetTests(_Base):
    def test_three_invalid_decisions_pause_before_fourth_model_retry(self):
        self.ask.side_effect = [json.dumps({'action': 'plan', 'goals': ['Listeyi incele']})] + [
            json.dumps({'action': 'tool', 'goal': 0, 'tool': 'action',
                'input': {'action': 'tasks_list', 'params': {}}, 'depends': ['missing-step']})] * 60
        with patch.object(goal_tools, 'execute', side_effect=AssertionError('Geçersiz bağımlılık yürütülmemeli')):
            reply = goals.run(self.runtime, 'Listeyi incele')
        job = goals.latest('alice')
        self.assertEqual(self.ask.call_count, 4)  # initial plan + three rejected decisions
        self.assertEqual(job['state'], 'paused')
        self.assertEqual(job['goals'][0]['text'], 'Listeyi incele')
        self.assertEqual(job['steps'], [])
        self.assertIn('3', reply)

    def test_total_budget_counts_multiple_planner_calls_in_same_turn(self):
        clock = [0.]
        def planner(*args):
            clock[0] += 41
            if clock[0] == 41:
                return {'action': 'plan', 'goals': ['Listeyi incele']}
            return {'action': 'tool', 'goal': 0, 'tool': 'action',
                'input': {'action': 'tasks_list', 'params': {}}, 'depends': ['missing-step']}
        with patch.object(goals, 'time', SimpleNamespace(time=time.time, monotonic=lambda: clock[0])), \
             patch.object(goals, '_planner', side_effect=planner) as calls:
            reply = goals.run(self.runtime, 'Listeyi incele')
        self.assertEqual(calls.call_count, 3)
        job = goals.latest('alice')
        self.assertEqual(job['state'], 'paused')
        self.assertIn('toplam', reply.casefold())
        self.assertEqual(job['outputs'], {})
        ident = job['id']
        with patch.object(goals, 'time', SimpleNamespace(time=time.time, monotonic=lambda: clock[0])), \
             patch.object(goals, '_planner', return_value={'action': 'ask', 'question': 'Hangi klasörde çalışayım?'}):
            goals.run(self.runtime, 'hedef devam', resume=True)
        resumed = goals.latest('alice')
        self.assertEqual(resumed['id'], ident)
        self.assertEqual(resumed['state'], 'question')

    def test_verified_new_output_resets_invalid_decision_allowance(self):
        invalid = {'action': 'tool', 'goal': 0, 'tool': 'action',
            'input': {'action': 'tasks_list', 'params': {}}, 'depends': ['missing-step']}
        valid = dict(invalid, depends=[])
        sequence = [{'action': 'plan', 'goals': ['Listeyi incele']}, invalid, invalid, valid,
                    invalid, invalid, RuntimeError('Taklit sağlayıcı durdu')]
        def record(runtime, job, step, approval=None):
            step['state'] = 'done'
            job['outputs'][step['id']] = {'state': 'done', 'text': 'Doğrulanmış örnek liste'}
            return job['outputs'][step['id']]
        with patch.object(goals, '_planner', side_effect=sequence) as calls, patch.object(goals, '_record', side_effect=record):
            goals.run(self.runtime, 'Listeyi incele')
        job = goals.latest('alice')
        self.assertEqual(calls.call_count, 7)
        self.assertEqual(job['state'], 'paused')
        self.assertEqual(job['outputs']['s1']['text'], 'Doğrulanmış örnek liste')


    def test_parent_turn_budget_interrupts_model_wait_and_ignores_late_plan(self):
        release = threading.Event()
        self.ask.side_effect = lambda *a, **k: (release.wait(1), json.dumps({'action': 'plan', 'goals': ['Geç gelen hedef']}))[1]
        with patch.object(goals, 'TURN_SECONDS', .03, create=True), patch.object(goals, 'PLANNER_SECONDS', .5):
            try:
                reply = goals.run(self.runtime, 'Listeyi incele')
                self.assertIn('toplam', reply.casefold())
                self.assertFalse(release.is_set())
            finally:
                release.set()
                deadline = time.monotonic() + 2
                while 'alice' in model_wait._PENDING and time.monotonic() < deadline:
                    time.sleep(.001)
        job = goals.latest('alice')
        self.assertEqual(job['state'], 'paused')
        self.assertEqual(job['goals'], [])
        self.assertNotIn('phase', job)
