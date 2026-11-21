"""Native Groq capacity failures must not poison smaller requests or retry unchanged input."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import failure_policy, llm, router_quota, smart_router
from provider_fixture import routed_plan
from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness


def response(status, payload):
    result = llm.requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.headers['retry-after'] = '0.001'
    return result


def too_large():
    return response(413, {'error': {
        'code': 'rate_limit_exceeded', 'type': 'tokens',
        'message': 'Request too large on tokens per minute (TPM): Limit 8000, Requested 10479. '
                   'org_PRIVATE api_key=sk-PRIVATE user@example.org',
    }})


def success():
    return response(200, {'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                          'usage': {'prompt_tokens': 4, 'completion_tokens': 3, 'total_tokens': 7}})


class GroqRequestCapacityTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(smart_router, '_STORE', directory))
        self.enterContext(patch.object(smart_router, '_HEALTH', {}))
        self.enterContext(patch.object(llm, '_rate_limited', {}))
        self.enterContext(patch.object(llm, 'user_groq_key', return_value='fixture-key'))
        self.enterContext(patch.object(llm.privacy, 'mode', return_value='normal'))
        self.enterContext(llm.owner_context('alice'))
        self.spec = smart_router.ModelSpec('groq', 'capacity-fixture')
        self.request = smart_router.ModelRequest(owner='alice', profile='conversation', max_output_tokens=2048)

    def run_native(self, *, prompt='synthetic input', validator=None):
        return smart_router.run_request(self.request, lambda spec: llm.dispatch(
            self.request, spec, prompt, 'synthetic system'), validator=validator)

    def test_short_brain_turns_fit_a_smaller_wire_contract_without_extra_attempts(self):
        from modules import brain_core_map, brain_model_understanding as brain
        from test_brain_primary_understanding import action, deterministic, envelope

        spec = smart_router.ModelSpec('groq', 'openai/gpt-oss-120b')
        plan = smart_router.RoutePlan((spec,), (), 2)
        past = tuple({'id': str(i), 'role': 'assistant', 'text': 'Haber özeti ' * 50}
                     for i in range(8))
        cases = (
            ('naber', envelope(operation='chat'), None),
            ('youtube aç', envelope(actions=[action(
                capability_id='media.search', arguments={'service': 'youtube_home'})]),
             'media_search'),
        )

        with patch.object(smart_router, 'plan', return_value=plan):
            for text, raw, intent in cases:
                with self.subTest(text=text), patch.object(
                    llm.requests, 'post', return_value=response(200, {
                        'choices': [{'message': {'content': raw}, 'finish_reason': 'stop'}],
                    }),
                ) as post:
                    proposal = brain.propose(owner='alice', text=text, current=deterministic(text),
                                             arguments={}, recent_turns=past)
                    self.assertIsNotNone(proposal)
                    post.assert_called_once()
                    body = post.call_args.kwargs['json']
                    system, user = (item['content'] for item in body['messages'])
                    payload = json.loads(user)
                    self.assertLess(len(system) + len(user), 25000)
                    self.assertEqual(body['max_tokens'], 2048)
                    self.assertEqual(set(payload['required']), brain.ENVELOPE_KEYS)
                    self.assertEqual(set(payload['allowed']['argument_schema']),
                                     set(brain_core_map.CORE_INTENTS) - brain._MODEL_DENIED_CAPABILITIES
                                     - {'documents.export'})
                    self.assertEqual(payload['allowed']['argument_schema']['message.send']['argument_sources'],
                                     ['recipient', 'body'])
                    self.assertEqual([row['id'] for row in payload['recent_turns']], ['4', '5', '6', '7'])
                    self.assertTrue(all(len(row['text']) <= 180 for row in payload['recent_turns']))
                    if intent:
                        proposed = proposal.actions[0]
                        self.assertEqual(brain_core_map.core_plan(proposed.capability_id, proposed.arguments),
                                         (intent, {'service': 'youtube_home'}))
                    else:
                        self.assertEqual(proposal.operation, 'chat')
                        self.assertEqual(proposal.actions, ())

    def test_native_413_retains_capacity_status_and_safe_provider_counts(self):
        with patch.object(llm.requests, 'post', return_value=too_large()):
            with self.assertRaises(Exception) as caught:
                llm._groq([], '', 2048, model=self.spec.model)
        error = caught.exception
        self.assertEqual(failure_policy.classify(error), 'request_limit')
        self.assertEqual(failure_policy.status_code(error), 413)
        self.assertEqual(failure_policy.reason_code(error), 'PROVIDER_REQUEST_TOO_LARGE')
        self.assertEqual((error.limit, error.requested), (8000, 10479))
        self.assertFalse(failure_policy.is_transient(error))
        self.assertEqual(failure_policy.cooldown_seconds('groq', error), 0)
        self.assertNotIn('PRIVATE', str(error))
        self.assertNotIn('user@example.org', str(error))

    def test_unchanged_request_is_not_retried_and_smaller_request_stays_eligible(self):
        plan = smart_router.RoutePlan((self.spec,), (), 2)
        with patch.object(smart_router, 'plan', return_value=plan), \
                patch.object(llm.requests, 'post', side_effect=[too_large(), success()]) as post:
            with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
                self.run_native(prompt='Synthetic larger context. ' * 1000, validator=json.loads)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(caught.exception.reason_code, 'PROVIDER_REQUEST_TOO_LARGE')
            self.assertEqual(smart_router._HEALTH, {})
            self.assertEqual(llm._rate_limited, {})
            trace = router_quota.recent_traces('alice', directory=smart_router._STORE)[0]
            self.assertEqual(trace['attempts'][0]['status'], 413)
            self.assertEqual(trace['attempts'][0]['limit_kind'], 'tokens_per_minute')
            self.assertEqual((trace['attempts'][0]['limit'], trace['attempts'][0]['requested']), (8000, 10479))
            self.assertNotIn('PRIVATE', json.dumps(trace))
            self.assertNotIn('fixture-key', json.dumps(trace))
            self.assertEqual(self.run_native(prompt='Short reply.').text, '{"ok":true}')
            self.assertEqual(post.call_count, 2)
            sent = [call.kwargs['json']['messages'][-1]['content'] for call in post.call_args_list]
            self.assertGreater(len(sent[0]), len(sent[1]))

    def test_eligible_fallback_uses_only_the_remaining_physical_attempt(self):
        fallback = smart_router.ModelSpec('ollama', 'local-fixture')
        plan = smart_router.RoutePlan((self.spec, fallback), (), 2)
        calls = []

        def adapter(spec):
            calls.append(spec.provider)
            if spec.provider == 'groq':
                return llm.dispatch(self.request, spec, 'synthetic', '')
            return 'fallback result'

        with patch.object(smart_router, 'plan', return_value=plan), \
                patch.object(llm.requests, 'post', return_value=too_large()) as post:
            result = smart_router.run_request(self.request, adapter)
        self.assertEqual(calls, ['groq', 'ollama'])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0]['kind'], 'request_limit')
        self.assertEqual(result.attempts[0]['status'], 413)
        self.assertEqual(smart_router._HEALTH, {})

    def test_non_json_413_is_not_reported_as_empty_model_output(self):
        result = response(413, {})
        result._content = b'payload too large - PRIVATE'
        with patch.object(llm.requests, 'post', return_value=result):
            with self.assertRaises(Exception) as caught:
                llm._groq([], '', 2048, model=self.spec.model)
        self.assertEqual(failure_policy.classify(caught.exception), 'request_limit')
        self.assertIsNone(caught.exception.limit)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_full_holdout_reports_capacity_and_stops_without_a_model_response(self):
        from test_brain_output_diagnose_holdout import runner
        plan = smart_router.RoutePlan((self.spec,), (), 2)
        cases = [{'id': 'c1', 'group': 'chat', 'text': 'Merhaba', 'expected': ['chat'], 'has_output': False},
                 {'id': 'c2', 'group': 'chat', 'text': 'Selam', 'expected': ['chat'], 'has_output': False}]
        with patch.object(smart_router, 'plan', return_value=plan), \
                patch.object(llm.requests, 'post', return_value=too_large()) as post:
            result = runner.measure('alice', cases, interval_seconds=0)
        self.assertEqual(result['state'], 'unmeasured')
        self.assertEqual(result['stop_reason'], 'provider_request_too_large')
        self.assertEqual(result['provider_requests'], 1)
        self.assertEqual(result['provider_responses'], 0)
        self.assertEqual(result['attempted_effects'], 0)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['results'][0]['proposal_diagnostic']['reason_code'], 'PROVIDER_REQUEST_TOO_LARGE')


class BrainRequestCapacityRefusalTests(_CanonicalAuthorityHarness):
    def test_quota_and_size_failure_reaches_the_user_without_effects(self):
        plan = smart_router.RoutePlan((smart_router.ModelSpec('gemini', 'primary'),
                                       smart_router.ModelSpec('groq', 'backup')), (), 2)
        quota = llm.requests.HTTPError('daily quota', response=response(429, {}))
        oversized = failure_policy.ProviderRequestLimitError(provider='groq', status_code=413,
                                                            limit=8000, requested=13314)
        with routed_plan(), patch.object(smart_router, 'plan', return_value=plan), \
             patch.object(llm, 'dispatch', side_effect=[quota, oversized]) as dispatch:
            entry, output, _handler, feedback = self.turn_real('YouTube aç', model_understanding=True)
        self.assertEqual(dispatch.call_count, 2)
        self.assertIn('PROVIDER_QUOTA_AND_REQUEST_TOO_LARGE', entry.understanding.reason_codes)
        self.assertEqual(feedback.reason_code, 'PROVIDER_QUOTA_AND_REQUEST_TOO_LARGE')
        self.assertIn('kota sınırına', output)
        self.assertIn('isteğin boyutunu', output)
        self.run_goal.assert_not_called()

    def test_real_brain_core_turn_reports_capacity_without_starting_effects(self):
        with routed_plan(provider='groq', model='capacity-fixture', count=2), \
                patch.object(llm, '_rate_limited', {}), \
                patch.object(llm, 'user_groq_key', return_value='fixture-key'), \
                patch.object(llm.privacy, 'mode', return_value='normal'), \
                patch.object(llm.requests, 'post', return_value=too_large()) as post:
            entry, output, _handler, feedback = self.turn_real('Yeni bir not ekle', model_understanding=True)
        self.assertIn('MODEL_UNAVAILABLE', entry.understanding.reason_codes)
        self.assertIn('PROVIDER_REQUEST_TOO_LARGE', entry.understanding.reason_codes)
        self.assertEqual(feedback.result_status, 'failed')
        self.assertEqual(feedback.reason_code, 'PROVIDER_REQUEST_TOO_LARGE')
        self.assertEqual(feedback.recovery_class, 'request_change_required')
        self.assertIn('modelin istek sınırını aşıyor', output)
        self.assertEqual(post.call_count, 1)
        self.run_goal.assert_not_called()
        self.ctx.output.save_text_result.assert_not_called()


if __name__ == '__main__':
    unittest.main()
