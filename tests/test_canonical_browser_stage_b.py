"""Aşama B: etkileşimli tarayıcı kök görevinin canonical admission sözleşmeleri.

Fiziksel Playwright çalıştırılmaz; motor (browser_agent) ve worker hattı
taklit edilir. Core kartları, duraklama bağlama ve receipt fences gerçek
Scheduler/GoalState/ExecutionRecord üzerinden doğrulanır.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_canonical_effectful_scheduler import CanonicalEffectfulSchedulerTests as _Harness
from modules import (
    browser_agent, canonical_goal_control, canonical_goal_flow,
    canonical_restart_audit, canonical_scheduler_dispatch, goal_executor,
    goal_plan_gate, goal_tools, runtime_prepare_approval, task_plan_contracts,
    task_results, task_workers, task_tools,
)

URL = 'https://example.org/form'
INPUT = {'url': URL, 'instruction': 'Ara kutusuna merhaba yaz ve gönder',
         'mode': 'interactive'}
PAUSE_MESSAGE = ("İşlem planı hazır: [{\"op\":\"click\",\"selector\":\"#send\"}]. "
                 "Bu plan yalnız hedefin Core onay kartıyla uygulanır; "
                 "vazgeçmek için ‘tarayıcı iptal’ yaz.")


def engine_pause(token='a1b2c3d4e5f6'):
    return {'state': 'approval', 'id': token, 'action': 'click',
            'url': URL, 'message': PAUSE_MESSAGE}


def effect_done(image):
    return {'state': 'done', 'steps': [
        {'op': 'goto', 'url': URL, 'verified': True},
        {'op': 'click', 'selector': '#send', 'verified': True}],
        'page': {'url': URL, 'title': 'Form'}, 'image': str(image)}


class ContractTests(unittest.TestCase):
    def temp_image(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = pathlib.Path(temp.name) / 'shot.png'
        path.write_bytes(b'mocked-native-browser-image')
        return path

    def test_interactive_mode_passes_catalog_validation(self):
        data = {'url': URL, 'instruction': 'Formu doldur', 'mode': 'interactive'}
        self.assertEqual(task_tools.validate_input('browser', data), data)

    def test_catalog_rejects_unknown_or_empty_mode(self):
        for mode in ('execute', 'RO', ''):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                task_tools.validate_input(
                    'browser', {'url': URL, 'instruction': 'x', 'mode': mode})

    def test_gate_admits_alone_interactive_or_readonly_root(self):
        for mode in ('interactive', 'readonly'):
            node = {'id': 'b', 'capability_id': 'task.browser',
                    'input': dict(INPUT, mode=mode), 'depends_on': []}
            with self.subTest(mode=mode):
                self.assertTrue(goal_plan_gate._effect_node_allowed(
                    {'nodes': [node]}, node))

    def test_gate_rejects_browser_with_dependency(self):
        dep = {'id': 'a', 'capability_id': 'task.research',
               'input': {'query': 'x'}, 'depends_on': []}
        node = {'id': 'b', 'capability_id': 'task.browser',
                'input': dict(INPUT), 'depends_on': ['a']}
        self.assertFalse(goal_plan_gate._effect_node_allowed(
            {'nodes': [dep, node]}, node))

    def test_gate_rejects_missing_or_unknown_mode(self):
        for mode in (None, 'execute'):
            data = {'url': URL, 'instruction': 'x'}
            if mode is not None:
                data['mode'] = mode
            node = {'id': 'b', 'capability_id': 'task.browser',
                    'input': data, 'depends_on': []}
            with self.subTest(mode=mode), self.assertRaisesRegex(
                    ValueError, 'readonly'):
                canonical_goal_flow._canonical_plan(
                    [{'id': 'b', 'agent': 'browser', 'depends': [],
                      'input': data}], allow_effects=True)

    def test_receipt_binds_executed_plan_deterministically(self):
        image = self.temp_image()
        first = task_results.browser_effect_receipt(effect_done(image))
        second = task_results.browser_effect_receipt(effect_done(image))
        self.assertEqual(first, second)
        self.assertEqual(first['service'], 'browser_agent_effect')
        output = effect_done(image)
        payload = json.dumps(
            {'steps': output['steps'], 'page': output['page'],
             'image': hashlib.sha256(image.read_bytes()).hexdigest()},
            ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            allow_nan=False).encode('utf-8')
        self.assertEqual(first['remote_id'],
                         hashlib.sha256(payload).hexdigest())
        # A changed executed plan (new selector) changes the receipt identity.
        changed = {**output, 'steps': output['steps'][:1] + [
            {'op': 'click', 'selector': '#other', 'verified': True}]}
        self.assertNotEqual(first['remote_id'],
                            task_results.browser_effect_receipt(changed)['remote_id'])
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        override = task_results.browser_effect_receipt(
            dict(effect_done(None), image='gone.png', image_sha256=digest))
        self.assertEqual(override['remote_id'],
                         first['remote_id'])

    def test_receipt_rejects_incomplete_or_readonly_shapes(self):
        image = self.temp_image()
        cases = [
            dict(effect_done(image), readonly=True),
            {**effect_done(image), 'steps': []},
            {'state': 'running', 'steps': [{'op': 'goto', 'verified': True}],
             'page': {'url': URL}, 'image': str(image)},
            {'state': 'done', 'page': {'url': URL}, 'image': str(image)},
            {'state': 'done', 'steps': [{'op': 'read', 'verified': True}],
             'image': str(image)},
            {'state': 'done', 'steps': [{'op': 'read', 'verified': True}],
             'page': {'url': URL}},
        ]
        for output in cases:
            with self.subTest(state=output.get('state'),
                              readonly=output.get('readonly')), \
                    self.assertRaises(ValueError):
                task_results.browser_effect_receipt(output)

    def test_prepare_card_describes_browser_not_desktop(self):
        card = runtime_prepare_approval.prepare(
            {'owner': 'alice', 'job_id': 'j1', 'task_id': 'b'}, 'browser',
            dict(INPUT))
        self.assertEqual(card['state'], 'approval')
        self.assertIn('Tarayıcı gerçek sayfada', card['text'])
        self.assertNotIn('PC görevi', card['text'])
        self.assertTrue(runtime_prepare_approval.accept(
            card, {'owner': 'alice', 'job_id': 'j1', 'task_id': 'b'},
            'browser', dict(INPUT)))

    def test_legacy_approval_and_bound_resume_never_coexist(self):
        identity = {'owner': 'alice', 'job_id': 'j', 'task_id': 'b',
                    '_canonical_browser_resume': 'a1b2c3d4e5f6'}
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice', data={}))
        from modules import untrusted_flow
        with patch.object(untrusted_flow, 'observe'):
            with self.assertRaisesRegex(ValueError, 'çakışıyor'):
                goal_tools.execute(runtime, 'browser', dict(INPUT), {}, identity,
                                   approval='a1b2c3d4e5f6')

    def test_planner_note_advertises_interactive_browser(self):
        note = task_plan_contracts.CANONICAL_EFFECT_NOTE
        self.assertIn('mode":"interactive"', note)
        self.assertIn('model onay üretemez', note)
        self.assertIn('yalnız bağımsız kök görevdir', note)


class BrowserPlanAdmissionTests(unittest.TestCase):
    def test_interactive_browser_root_admitted_as_task_browser(self):
        plan = canonical_goal_flow._canonical_plan(
            [{'id': 'browse', 'agent': 'browser', 'depends': [],
              'input': dict(INPUT)}], allow_effects=True)
        self.assertEqual(plan['nodes'][0]['capability_id'], 'task.browser')

    def test_interactive_browser_with_dependency_rejected(self):
        with self.assertRaises(ValueError):
            canonical_goal_flow._canonical_plan([
                {'id': 'read', 'agent': 'research', 'depends': [],
                 'input': {'query': 'x'}},
                {'id': 'browse', 'agent': 'browser', 'depends': ['read'],
                 'input': dict(INPUT)},
            ], allow_effects=True)


class StageBHarness(_Harness):
    """Scheduler harnessı; taban sınıf keşfe kapalı tutulur."""
    __test__ = False

    def run_offer(self, ident):
        return canonical_scheduler_dispatch.execute_offer(
            SimpleNamespace(slug=self.owner), self.offer(ident),
        )

    def create_interactive(self):
        return self.create({'id': 'browse', 'agent': 'browser',
                            'input': dict(INPUT)},
                           'example.org formunu doldur ve gönder.')

    def approve_card(self, ident):
        shown = goal_executor.read_job(self.owner, ident)
        return canonical_goal_control.approve_effect(
            self.owner, ident, expected_control=goal_executor.control_key(shown))

    def to_pause(self, ident):
        """prepare kartı tüketilir; worker turu motorda duraklar."""
        with patch.object(task_workers, 'run', side_effect=AssertionError(
                'No browser before exact user approval')):
            self.assertFalse(self.run_offer(ident))
        self.approve_card(ident)
        with patch.object(task_workers, 'run', return_value=engine_pause()):
            self.assertFalse(self.run_offer(ident))


class InteractiveFlowTests(StageBHarness):
    def setUp(self):
        _Harness.setUp(self)

    def test_prepare_round_blocks_worker_and_shows_card(self):
        ident = self.create_interactive()
        with patch.object(task_workers, 'run', side_effect=AssertionError(
                'No browser before exact user approval')):
            self.assertFalse(self.run_offer(ident))
        shown = goal_executor.read_job(self.owner, ident)
        step = shown['steps'][0]
        self.assertEqual(step['state'], 'approval')
        self.assertEqual(shown['waiting'], 'browse')
        self.assertNotIn('_canonical_browser_token', step)
        card = step['_canonical_approval_proposal']['text']
        self.assertIn('Tarayıcı gerçek sayfada', card)
        self.assertIn(URL, card)
        self.assertIn('Her hassas işlem ayrıca durur', card)
        # The prepare card itself is approvable (attempt 0, not started).
        self.assertIn('değişmeyen browser', self.approve_card(ident))

    def test_pause_round_binds_token_and_fresh_plan_card(self):
        ident = self.create_interactive()
        self.to_pause(ident)
        shown = goal_executor.read_job(self.owner, ident)
        step = shown['steps'][0]
        self.assertEqual(step['state'], 'approval')
        self.assertEqual(step['attempts'], 1)
        self.assertTrue(step['started'])
        self.assertEqual(step['_canonical_browser_token'], 'a1b2c3d4e5f6')
        card = step['_canonical_approval_proposal']['text']
        self.assertIn('İşlem planı hazır', card)
        self.assertNotIn('tarayıcı onayla', card)
        # Aşama C: the engine never offers a second approval channel.
        self.assertIn('yalnız hedefin Core onay kartıyla uygulanır', card)
        self.assertIn('tarayıcı iptal', card)
        self.assertIn('Onay gerekli: browser / ' + URL, shown['blocker'])
        state, journal = self.snapshots(ident)
        self.assertEqual(state['evidence'], [])
        self.assertNotIn('browse', journal.get('outputs', {}))
        # An unconsumed pause card may not be re-offered to the Scheduler.
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())

    def test_full_pause_consume_resume_commits_evidence(self):
        ident = self.create_interactive()
        self.to_pause(ident)
        self.approve_card(ident)
        image = self.root / 'browser-effect.png'
        image.write_bytes(b'mocked-native-browser-image')
        with patch.object(browser_agent, 'run',
                          return_value=effect_done(image)) as engine:
            self.assertTrue(self.run_offer(ident))
        engine.assert_called_once_with(self.owner, approval='a1b2c3d4e5f6')
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'][0]['capability_id'], 'task.browser')
        self.assertEqual(state['evidence'][0]['command_id'], 'browse:1:p1')
        output = record['outputs']['browse']
        self.assertEqual(output['state'], 'done')
        self.assertTrue(task_results.verify(output, owner=self.owner))
        self.assertEqual(output['receipt'],
                         task_results.browser_effect_receipt(output))
        self.assertEqual(output['image_sha256'],
                         task_results.file_digest(image))
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())

    def test_restart_audit_recognizes_bound_pause_card(self):
        ident = self.create_interactive()
        self.to_pause(ident)
        snapshot = canonical_restart_audit.inspect(self.owner, ident)
        self.assertEqual(snapshot.nodes[0].status, 'approval_pending')
        # A started approval card without its bound native token is untrusted.
        job = goal_executor.read_job(self.owner, ident)
        job['steps'][0].pop('_canonical_browser_token')
        goal_executor._save(job)
        with self.assertRaises(canonical_restart_audit.RestartAuditError):
            canonical_restart_audit.inspect(self.owner, ident)

    def test_started_card_without_token_is_not_approvable(self):
        ident = self.create_interactive()
        self.to_pause(ident)
        job = goal_executor.read_job(self.owner, ident)
        job['steps'][0].pop('_canonical_browser_token')
        goal_executor._save(job)
        shown = goal_executor.read_job(self.owner, ident)
        with self.assertRaisesRegex(PermissionError, 'Başlamış effect'):
            canonical_goal_control.approve_effect(
                self.owner, ident,
                expected_control=goal_executor.control_key(shown))

    def test_effect_done_without_receipt_is_rejected(self):
        ident = self.create_interactive()
        image = self.root / 'round-effect.png'
        image.write_bytes(b'mocked-native-browser-image')
        output = task_results.seal('browser', effect_done(image))
        self.reject_finished_round(ident, output)

    def test_forged_effect_receipt_is_rejected(self):
        ident = self.create_interactive()
        image = self.root / 'round-effect.png'
        image.write_bytes(b'mocked-native-browser-image')
        output = task_results.seal('browser', effect_done(image))
        output['receipt'] = {'service': 'browser_agent_effect',
                             'remote_id': 'deadbeef'}
        self.reject_finished_round(ident, output)

    def test_readonly_flagged_output_needs_matching_readonly_receipt(self):
        # A readonly-labelled done on the interactive lane either carries its
        # exact observation receipt (legitimate read-only completion) or is
        # rejected by the shared evidence contract.
        ident = self.create_interactive()
        output = {'state': 'done', 'readonly': True, 'steps': [
            {'op': 'goto', 'url': URL, 'verified': True},
            {'op': 'read', 'url': URL, 'verified': True}],
            'page': {'url': URL, 'title': 'Form'}}
        with patch.object(task_workers, 'run', side_effect=AssertionError(
                'No browser before exact user approval')):
            self.assertFalse(self.run_offer(ident))
        self.approve_card(ident)
        with patch.object(task_workers, 'run', return_value=output):
            with self.assertRaisesRegex(ValueError, 'receipt'):
                self.run_offer(ident)

    def test_real_browser_task_passthrough_and_receipt_tail(self):
        # Yalnız browser_agent.run/llm.ask taklitli gerçek task_workers yolu:
        # hassas işlemde duraklama WorkerResult değildir; done turu ekran
        # digest'i + effect receipt ekler.
        from modules import llm as llm_module
        image = self.root / 'worker-shot.png'
        image.write_bytes(b'mocked-native-browser-image')
        initial = {'state': 'done', 'page': {'url': URL, 'title': 'Form'}}
        plan = json.dumps({'actions': [
            {'op': 'click', 'selector': '#send', 'expect_url': URL}]})
        with patch.object(llm_module, 'ask', return_value=plan), \
                patch.object(browser_agent, 'run',
                             side_effect=[initial, engine_pause()]):
            self.assertEqual(
                task_workers.browser_task(self.owner, dict(INPUT)),
                engine_pause())
        finished = {'state': 'done', 'steps': [
            {'op': 'goto', 'url': URL, 'verified': True},
            {'op': 'click', 'selector': '#send', 'verified': True}],
            'page': {'url': URL, 'title': 'Form'}, 'image': str(image)}
        with patch.object(llm_module, 'ask', return_value=plan), \
                patch.object(browser_agent, 'run',
                             side_effect=[initial, finished]):
            sealed = task_workers.browser_task(self.owner, dict(INPUT))
        self.assertEqual(sealed['image_sha256'],
                         task_results.file_digest(image))
        self.assertEqual(sealed['receipt'],
                         task_results.browser_effect_receipt(sealed))

    def reject_finished_round(self, ident, output):
        with patch.object(task_workers, 'run', side_effect=AssertionError(
                'No browser before exact user approval')):
            self.assertFalse(self.run_offer(ident))
        self.approve_card(ident)
        with patch.object(task_workers, 'run', return_value=output):
            with self.assertRaisesRegex(PermissionError, 'readonly'):
                self.run_offer(ident)
        state, record = self.snapshots(ident)
        self.assertEqual(state['evidence'], [])
        # The guard fire means the effect round is unknown, never accepted.
        self.assertEqual(
            record['outputs']['browse'],
            {'state': 'failed',
             'text': 'Canonical worker stopped; manual review required. '
                     'No effect retried.',
             'reason_code': 'CANONICAL_PROVIDER_RESULT_UNKNOWN_UNACCEPTED'})

    def test_stale_plan_input_change_blocks_resume_round(self):
        # The engine's pending token is bound to the exact node input; a plan
        # revision that changes the input drops the resume binding eligibility.
        ident = self.create_interactive()
        self.to_pause(ident)
        job = goal_executor.read_job(self.owner, ident)
        step = job['steps'][0]
        step['_canonical_browser_token'] = ''
        goal_executor._save(job)
        shown = goal_executor.read_job(self.owner, ident)
        with self.assertRaisesRegex(PermissionError, 'Başlamış effect'):
            canonical_goal_control.approve_effect(
                self.owner, ident,
                expected_control=goal_executor.control_key(shown))


if __name__ == '__main__':
    unittest.main()
