"""BRAIN-05 goal holdout contracts; never call a real model or OS effect."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import brain_goal_holdout as goal

class GoalHoldoutTests(unittest.TestCase):
    def test_corpus_has_exactly_twenty_synthetic_nonexecuting_cases(self):
        data = json.loads(goal.CORPUS.read_text(encoding='utf-8'))
        cases = data['cases']
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({r['id'] for r in cases}), 20)
        self.assertTrue(any(r['expected']['operation']=='clarify' for r in cases))
        self.assertTrue(any(r['expected']['operation']=='create_goal' for r in cases))
        allowed = {'create_goal','continue_goal','revise_goal','add_task','pause_goal',
                   'resume_goal','cancel_goal','prioritize_goal','clarify','chat'}
        for row in cases:
            self.assertIn(row['expected']['operation'], allowed)
            ids = {g['id'] for g in row['goals']}
            self.assertTrue(set(row['expected']['targets']) <= ids)
            self.assertTrue(all(len(g['id']) == 16 for g in row['goals']))

    def test_fresh_suite_is_independent_and_never_uses_real_goals(self):
        baseline = json.loads(goal.CORPUS.read_text(encoding='utf-8'))['cases']
        fresh = json.loads(goal.FRESH_CORPUS.read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(fresh),20)
        self.assertEqual(len({x['id'] for x in fresh}),20)
        self.assertFalse({x['text'] for x in baseline} & {x['text'] for x in fresh})
        self.assertFalse({x['id'] for x in baseline} & {x['id'] for x in fresh})
        self.assertTrue(all(x['id'].startswith('g05f-') for x in fresh))
        allowed = {'create_goal','continue_goal','revise_goal','add_task','pause_goal',
                   'resume_goal','cancel_goal','prioritize_goal','clarify','chat'}
        for row in fresh:
            self.assertIn(row['expected']['operation'],allowed)
            goals = row['goals']
            self.assertTrue(all(len(g['id'])==16 and g['id'] in {'1111111111111111','2222222222222222'} for g in goals))
            self.assertTrue(set(row['expected']['targets']) <= {g['id'] for g in goals})
        self.assertEqual([x['expected']['operation'] for x in fresh].count('chat'),2)
        self.assertEqual([x['expected']['operation'] for x in fresh].count('clarify'),2)

    def test_fresh_suite_dry_run_does_not_call_preflight_or_dispatch(self):
        with patch.object(goal.base,'preflight',side_effect=AssertionError('must not run')), \
             patch.object(goal,'measure',side_effect=AssertionError('must not run')):
            self.assertEqual(goal.main(['--suite','fresh']),0)

    def test_scoring_rejects_wrong_target_even_when_operation_correct(self):
        case = json.loads(goal.CORPUS.read_text(encoding='utf-8'))['cases'][5]
        self.assertEqual(case['expected']['operation'], 'pause_goal')
        correct = SimpleNamespace(operation='pause_goal',target_goal_ids=('aaaaaaaaaaaaaaaa',),
                                  goal=None, actions=())
        wrong = SimpleNamespace(operation='pause_goal',target_goal_ids=('bbbbbbbbbbbbbbbb',),
                                goal=None, actions=())
        self.assertTrue(goal.judge(case,correct)['correct'])
        verdict = goal.judge(case,wrong)
        self.assertFalse(verdict['correct'])
        self.assertTrue(verdict['incorrect_action_proposal'])

    def test_create_requires_goal_card_and_no_target(self):
        case = json.loads(goal.CORPUS.read_text(encoding='utf-8'))['cases'][0]
        good = SimpleNamespace(operation='create_goal',target_goal_ids=(),
                               goal={'kind':'goal','title':'synthetic'},actions=())
        bad = SimpleNamespace(operation='create_goal',target_goal_ids=(),goal=None,actions=())
        self.assertTrue(goal.judge(case,good)['correct'])
        self.assertTrue(goal.judge(case,bad)['incorrect_action_proposal'])

    def test_goal_candidates_are_synthetic_owner_bound_observations(self):
        case = json.loads(goal.CORPUS.read_text(encoding='utf-8'))['cases'][5]
        from modules.brain_understanding import understand
        with patch('modules.brain_model_understanding.propose', return_value=None) as propose:
            goal.ask('alice',case,1)
        cards = propose.call_args.kwargs['goal_candidates']
        self.assertEqual([c.id for c in cards], ['aaaaaaaaaaaaaaaa','bbbbbbbbbbbbbbbb'])
        self.assertTrue(all(c.owner=='alice' for c in cards))
        self.assertEqual(cards[0].provenance['title'], 'sunum taslağı')

    def test_goal_prompt_separates_goal_operation_from_turn_relation(self):
        from modules import brain_model_understanding as model, llm, smart_router
        case = json.loads(goal.CORPUS.read_text(encoding='utf-8'))['cases'][2]
        with patch.object(llm, 'current_user', return_value='alice'), \
             patch.object(llm, 'provider', return_value='groq'), \
             patch.object(llm.privacy, 'mode', return_value='normal'), \
             patch.object(smart_router, 'selection', return_value={'candidates':['groq']}), \
             patch.object(smart_router, 'run', return_value='{}') as fake:
            self.assertIsNone(goal.ask('alice', case, 3))
        sent = fake.call_args.args[1]
        self.assertIn('GOAL OUTPUT CONTRACT', sent)
        self.assertIn('COPY current.conversation_relation exactly', sent)
        self.assertIn('For continue_goal, revise_goal, add_task', sent)
        self.assertIn('FINAL JSON CONTRACT CHECK', sent)
        self.assertIn('GOAL PRIORITY VS REVISION', sent)
        self.assertIn('GOAL NEGATION SAFETY', sent)
        self.assertIn("the ONLY allowed operation is chat", sent)

    def test_dry_run_never_checks_credentials_or_sends_models(self):
        with patch.object(goal.base,'preflight',side_effect=AssertionError('should not run')), \
             patch.object(goal,'measure',side_effect=AssertionError('should not run')):
            self.assertEqual(goal.main([]),0)

    def test_runner_reuses_exact_effect_guard_and_verdict(self):
        with patch.object(goal.base,'measure',return_value={'state':'unmeasured'}) as measure:
            self.assertEqual(goal.measure('alice',[],interval_seconds=0),{'state':'unmeasured'})
        measure.assert_called_once()

if __name__ == '__main__':
    unittest.main()
