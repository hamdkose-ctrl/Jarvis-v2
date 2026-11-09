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
    def test_response_metadata_does_not_retain_unknown_keys_or_values(self):
        from modules.brain_model_understanding import SCHEMA_VERSION
        data=runner.response_shape(json.dumps({SCHEMA_VERSION:{'SECRET_KEY':'SECRET_TEXT'}}))
        self.assertTrue(data['named_wrapper']);self.assertFalse(data['version_matches'])
        self.assertEqual(data['extra_field_count'],1)
        self.assertNotIn('SECRET',repr(data))
        self.assertEqual(runner.response_shape('not json SECRET'),{'json_object':False})

    def test_a_rejected_raw_wrong_action_is_still_a_critical_proposal(self):
        from modules import llm, brain_model_understanding as model
        def rejected(*args):
            llm._send_provider('groq','synthetic','synthetic',2048,None)
            model._proposal_diagnostic.set({'status':'rejected','reason_code':'CORE_ARGUMENTS_INVALID',
                'operation':'direct_action','capabilities':['documents.export']})
            return None
        with patch('modules.llm._send_provider',return_value='{}'),patch.object(runner,'ask',side_effect=rejected):
            result=runner.measure('owner',[self.case(['chat'])])
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['incorrect_action_proposals'],1)

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

    def test_connection_probe_spends_one_case_without_claiming_semantic_acceptance(self):
        measured=runner.verdict([runner.judge(self.case(['chat']),proposal('direct_action','system.diagnose'))],0)
        measured.update(provider_requests=1,provider_responses=1,
                        results=[runner.judge(self.case(['chat']),proposal('direct_action','system.diagnose'))])
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/'report.json'
            with patch.object(runner,'preflight',return_value=('owner',True,'ready')), patch.object(runner,'measure',return_value=measured) as run, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(['--run','--connection-only','--json',str(report)]),0)
            data=json.loads(report.read_text())
        self.assertEqual(len(run.call_args.args[1]),1)
        self.assertEqual(data['scope'],'connection');self.assertTrue(data['connection_ok'])
        self.assertFalse(data['semantic_acceptance'])
        self.assertNotIn('accuracy',data);self.assertNotIn('correct',data['results'][0])

    def test_local_deadline_and_a_silent_provider_get_different_stop_reasons(self):
        # Aynı 'yanıt yok' görünümü iki ayrı kök nedeni saklamaz: kendi süremiz dolduysa
        # ölçüm local_deadline_exceeded ile durur, sağlayıcı susmuşsa provider_no_response.
        from modules import brain_model_understanding as model
        for code, expected in [('LOCAL_DEADLINE_EXCEEDED','local_deadline_exceeded'),
                               ('MODEL_CALL_OR_VALIDATION_ERROR','provider_no_response')]:
            with self.subTest(reason_code=code):
                def expired(*args):
                    model._proposal_diagnostic.set({'status':'rejected','reason_code':code})
                    return None
                with patch.object(runner,'ask',side_effect=expired):
                    report=runner.measure('owner',[self.case(['chat'])]*20,interval_seconds=0)
                self.assertEqual(report['stop_reason'],expected)
                self.assertEqual(report['state'],'unmeasured')
                self.assertIsNone(report['accuracy'])
                self.assertEqual(report['incorrect_action_proposals'],0)
                self.assertEqual(report['attempted_effects'],0)

    def test_invalid_first_real_response_stops_the_full_run_as_failed(self):
        from modules import llm
        def invalid(*args):
            llm._send_provider('groq','synthetic','synthetic',2048,None)
            return None
        with patch('modules.llm._send_provider',return_value='invalid JSON'), patch.object(runner,'ask',side_effect=invalid) as ask:
            report=runner.measure('owner',[self.case(['chat'])]*20,interval_seconds=0)
        ask.assert_called_once()
        self.assertEqual(report['state'],'failed');self.assertIsNone(report['accuracy'])
        self.assertEqual(report['stop_reason'],'model_response_invalid')
        self.assertEqual(report['planned_cases'],20)

    def test_connection_probe_distinguishes_no_response_from_invalid_response(self):
        for responded, expected in [(False,'unmeasured'),(True,'failed')]:
            row=runner.judge(self.case(['chat']),None,response_received=responded)
            measured=runner.verdict([row],0)
            measured.update(provider_requests=1,provider_responses=int(responded),results=[row])
            with self.subTest(responded=responded), tempfile.TemporaryDirectory() as td:
                report=Path(td)/'report.json'
                with patch.object(runner,'preflight',return_value=('owner',True,'ready')), patch.object(runner,'measure',return_value=measured), redirect_stdout(io.StringIO()):
                    exit_code=runner.main(['--run','--connection-only','--json',str(report)])
                data=json.loads(report.read_text())
                self.assertEqual(data['state'],expected)
                self.assertEqual(exit_code,2 if not responded else 1)
                self.assertFalse(data['connection_ok']);self.assertFalse(data['semantic_acceptance'])

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

    def test_provider_reset_header_is_a_duration_not_an_utterance_rule(self):
        self.assertEqual(runner.reset_seconds('1m2.5s'),62.5)
        self.assertEqual(runner.reset_seconds('500ms'),.5)
        self.assertIsNone(runner.reset_seconds('unknown'))
        self.assertIsNone(runner.reset_seconds('-1s'))

    def test_real_response_observation_and_token_reset_spacing(self):
        from modules import llm
        def fake_response(*args):
            llm._send_provider('groq','synthetic','synthetic',1,None)
            return proposal()
        with patch('modules.llm._send_provider',return_value='{}'), patch.object(runner,'ask',side_effect=fake_response), patch('modules.usage_meter.limits',return_value={'groq':{'test-model':{'tok_reset':'1m'}}}), patch('modules.llm.groq_model',return_value='test-model'), patch.object(runner.time,'sleep') as sleep:
            r=runner.measure('owner',[self.case(['chat']),self.case(['chat'])])
        self.assertEqual(r['state'],'passed');self.assertEqual(r['provider_responses'],2)
        sleep.assert_called_once_with(61)

    def test_quota_stop_keeps_the_planned_count_without_a_success_rate(self):
        from modules import llm
        def response(owner,case,index):
            if index==0:
                llm._send_provider('groq','synthetic','synthetic',1,None)
                return proposal()
            return None
        with patch('modules.llm._send_provider',return_value='{}'), patch.object(runner,'ask',side_effect=response):
            r=runner.measure('owner',[self.case(['chat'])]*3,interval_seconds=0)
        self.assertEqual(r['state'],'unmeasured');self.assertIsNone(r['accuracy'])
        self.assertEqual(r['cases'],2);self.assertEqual(r['planned_cases'],3)

    def test_corpus_is_twenty_distinct_synthetic_eval_cases(self):
        rows=json.loads(runner.CORPUS.read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(rows),20);self.assertEqual(len({r['id'] for r in rows}),20)
        self.assertEqual({r['group'] for r in rows},{'export','diagnose','negation','explanation_or_quote','irony','missing_output'})

    def test_windows_workflow_declares_live_acceptance_instead_of_measuring_it(self):
        source=(ROOT/'.github/workflows/testler-windows.yml').read_text(encoding='utf-8')
        # Bu iş makinesinde canlı ölçüm hiç yapılmaz: otomatik çağrı, exit kodu eşlemesi ve
        # CI'da üretilmiş rapor artifact'ı yok. exit2'yi yeşile çevirmek ayrım değil,
        # aynı kanıtı iki kez saymaktır.
        self.assertNotIn('utf8 scripts/brain_output_diagnose_holdout.py',source)
        self.assertNotIn('--run --json',source)
        self.assertNotIn('$Exit',source)
        self.assertNotIn('brain-d4-',source)
        self.assertNotIn('upload-artifact',source)
        self.assertNotIn('continue-on-error',source)
        # Kalan beyan: kapanış için aynı SHA'nın gerçek kullanıcı Full raporu ayrıca gerekir.
        self.assertIn('GITHUB_STEP_SUMMARY',source)
        self.assertIn('state=passed',source)
        self.assertIn('Run-BrainCheck.ps1',source)
