"""Offline checks for the live measurement, never call an account/provider."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('d4_holdout',ROOT/'scripts/brain_output_diagnose_holdout.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def proposal(operation='chat', capability=None):
    return SimpleNamespace(operation=operation,actions=() if capability is None else (SimpleNamespace(capability_id=capability),))


class LiveHoldoutRunnerTests(unittest.TestCase):
    def case(self, expected, output=True):
        return {'id':'c1','group':'test','text':'synthetic','expected':expected,'has_output':output}

    def test_default_mode_never_accesses_an_account_or_model(self):
        with patch.object(runner,'preflight') as pre, patch.object(runner,'measure') as run, redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main([]),0)
        pre.assert_not_called(); run.assert_not_called()

    def test_missing_route_is_unmeasured_and_never_success(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'report.json'
            with patch.object(runner,'preflight',return_value=('owner',False,'no route')), patch.object(runner,'measure') as run, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(['--run','--json',str(report)]),2)
            data=json.loads(report.read_text())
        self.assertEqual(data['state'],'unmeasured');run.assert_not_called()
        self.assertNotIn('owner',data)

    def test_raw_model_proposal_is_required_for_a_score(self):
        row=runner.judge(self.case(['chat']),None)
        report=runner.verdict([row],0)
        self.assertEqual(report['state'],'unmeasured');self.assertIsNone(report['accuracy'])

    def test_an_ironic_comment_must_not_become_an_action(self):
        row=runner.judge(self.case(['chat','needs_input']),proposal('direct_action','system.diagnose'))
        report=runner.verdict([row],0)
        self.assertEqual(report['state'],'failed');self.assertEqual(report['incorrect_action_proposals'],1)

    def test_missing_output_requires_model_clarification_not_assumed_target(self):
        row=runner.judge(self.case(['needs_input'],False),proposal('direct_action','documents.export'))
        self.assertFalse(row['correct']);self.assertEqual(row['outcome'],'documents.export')

    def test_a_model_export_on_a_real_output_is_scored_as_an_action(self):
        row=runner.judge(self.case(['documents.export']),proposal('direct_action','documents.export'))
        self.assertEqual(runner.verdict([row],0)['state'],'passed')

    def test_an_attempted_effect_always_fails_the_measurement(self):
        row=runner.judge(self.case(['chat']),proposal())
        self.assertEqual(runner.verdict([row],1)['state'],'failed')

    def test_a_partial_set_cannot_claim_a_success_rate(self):
        rows=[runner.judge(self.case(['chat']),proposal()),runner.judge(self.case(['chat']),None)]
        r=runner.verdict(rows,0)
        self.assertIsNone(r['accuracy']);self.assertEqual(r['model_responses'],1)

    def test_a_received_but_invalid_model_response_is_failure_not_missing_access(self):
        row=runner.judge(self.case(['chat']),None,response_received=True)
        r=runner.verdict([row],0)
        self.assertEqual(r['state'],'failed');self.assertEqual(r['accuracy'],0)
        self.assertFalse(row['valid_proposal'])

    def test_measurement_intercepts_an_accidental_dispatch(self):
        from modules import engine_intents
        def attempt(*args):
            engine_intents.dispatch(None, 'document_export', {}, '', '')
        with patch.object(runner,'ask',side_effect=attempt):
            result=runner.measure('owner',[self.case(['chat'])])
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['attempted_effects'],1)
        self.assertEqual(result['provider_requests'],0)

    def test_expected_answers_are_not_sent_to_the_model_or_used_as_a_fallback(self):
        from modules.brain_contracts import ConversationRelation
        current=SimpleNamespace(arguments={},pending_owner=None,conversation_relation=ConversationRelation.NEW_REQUEST)
        with patch('modules.brain_understanding.understand',return_value=current), patch('modules.brain_model_understanding.propose',return_value=None) as model:
            self.assertIsNone(runner.ask('owner',self.case(['SECRET_EXPECTATION']),0))
        self.assertNotIn('SECRET_EXPECTATION',repr(model.call_args))
        self.assertEqual(model.call_args.kwargs['text'],'synthetic')

    def test_corpus_is_twenty_distinct_synthetic_eval_cases(self):
        rows=json.loads(runner.CORPUS.read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(rows),20);self.assertEqual(len({r['id'] for r in rows}),20)
        self.assertEqual({r['group'] for r in rows},{'export','diagnose','negation','explanation_or_quote','irony','missing_output'})

    def test_windows_workflow_runs_this_acceptance_only_for_its_changed_script(self):
        source=(ROOT/'.github/workflows/testler-windows.yml').read_text(encoding='utf-8')
        self.assertIn("$changed -contains 'scripts/brain_output_diagnose_holdout.py'",source)
        self.assertIn('brain_output_diagnose_holdout.py --run --json',source)
        self.assertIn('actions/upload-artifact@v4',source)
        self.assertIn('git checkout --detach $env:JARVIS_PR_HEAD_SHA',source)
