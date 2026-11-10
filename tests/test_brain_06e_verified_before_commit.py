"""BRAIN-06E: a worker's 'done' is NOT verified Core acceptance.

These tests force unverified worker and recovery observations at the actual
production adapter seams. They do not execute effects or claim global completion.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import (
    effect_recovery_runtime, reconcile_worker_result, specialist_orchestrator,
    worker_result_hook,
)


class VerifyBeforeCommitTests(unittest.TestCase):
    def test_regular_durable_worker_verifies_before_wrap(self):
        output = {'state': 'done', 'owner': 'alice', 'text': 'claimed success'}
        with (patch('modules.goal_tools.execute', return_value=output),
              patch('modules.goal_tools.verify', side_effect=ValueError('unverified')) as verify,
              patch.object(worker_result_hook, 'wrap_output') as wrap):
            with self.assertRaisesRegex(ValueError, 'unverified'):
                worker_result_hook.execute(None, 'research', {}, {}, {'owner': 'alice'})
        verify.assert_called_once_with(output, 'alice')
        wrap.assert_not_called()

    def test_verified_durable_worker_is_wrapped_as_before(self):
        output = {'state': 'done', 'owner': 'alice', 'text': 'verified'}
        with (patch('modules.goal_tools.execute', return_value=output),
              patch('modules.goal_tools.verify', return_value=True) as verify,
              patch.object(worker_result_hook, 'wrap_output', return_value={'sealed': True}) as wrap):
            result = worker_result_hook.execute(
                None, 'research', {}, {}, {'owner': 'alice'},
            )
        self.assertEqual(result, {'sealed': True})
        verify.assert_called_once_with(output, 'alice')
        wrap.assert_called_once_with(output, {'owner': 'alice'})

    def test_failed_worker_result_does_not_require_success_verification(self):
        output = {'state': 'failed', 'reason_code': 'UNAVAILABLE'}
        with (patch('modules.goal_tools.execute', return_value=output),
              patch('modules.goal_tools.verify') as verify,
              patch.object(worker_result_hook, 'wrap_output', return_value=output)):
            worker_result_hook.execute(None, 'research', {}, {}, {'owner': 'alice'})
        verify.assert_not_called()

    def _orchestrator(self, kind, request, *, phase='execute'):
        rt = SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        job = {'id': 'job1', 'owner': 'alice', 'request': request,
               'state': 'running', 'outputs': {}}
        step = {'id': 'read', 'tool': kind, 'input': {'url': 'https://example.test'},
                'depends': [], 'state': 'running'}
        identity = {'version': 1, 'owner': 'alice', 'job_id': 'job1',
                    'task_id': 'read', 'attempt': 1}
        return rt, job, step, identity

    def test_news_shortcut_rejects_unverified_done_before_cas(self):
        rt, job, step, identity = self._orchestrator('research', 'news request')
        output = {'state': 'done', 'owner': 'alice', 'text': 'fake news evidence'}
        with (patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase': 'execute'}),
              patch('modules.runtime_worker_result.prepare',
                    return_value=(identity, {'owner': 'alice'})),
              patch('modules.effect_recovery_runtime.required', return_value=False),
              patch('modules.research_evidence.news_requested', return_value=True),
              patch('modules.model_free_news.run', return_value=output),
              patch('modules.goal_tools.verify', side_effect=ValueError('unverified')),
              patch('modules.runtime_worker_result.accept_and_commit') as commit):
            with self.assertRaisesRegex(ValueError, 'unverified'):
                specialist_orchestrator._execute_step(rt, job, step, identity)
        commit.assert_not_called()

    def test_browser_prepare_does_not_commit_unverified_done(self):
        rt, job, step, identity = self._orchestrator('browser', 'open a page', phase='prepare')
        output = {'state': 'done', 'owner': 'alice', 'text': 'fake browser receipt'}
        with (patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase': 'prepare'}),
              patch('modules.goal_tools.execute', return_value=output),
              patch('modules.goal_tools.verify', side_effect=ValueError('unverified')),
              patch('modules.runtime_worker_result.accept_and_commit') as commit):
            with self.assertRaisesRegex(ValueError, 'unverified'):
                specialist_orchestrator._execute_step(rt, job, step, identity)
        commit.assert_not_called()

    def test_reconcile_rejects_unverified_done_before_fence_or_cas(self):
        output = {'state': 'done', 'owner': 'alice', 'text': 'unverified reconcile'}
        identity = {'version': 1, 'owner': 'alice'}
        with (patch('modules.goal_tools.verify', side_effect=ValueError('bad receipt')) as verify,
              patch.object(reconcile_worker_result, '_fence_expected',
                           return_value=(identity, {'owner': 'alice'})) as fence,
              patch('modules.runtime_worker_result.accept_and_commit') as commit):
            with self.assertRaisesRegex(ValueError, 'bad receipt'):
                reconcile_worker_result.accept_and_commit(
                    output, identity, 'research', {'url': 'https://example.test'},
                )
        verify.assert_called_once_with(output, 'alice')
        fence.assert_called_once()
        commit.assert_not_called()

    def test_reconcile_stale_execution_fence_blocks_readback(self):
        output = {'state': 'done', 'owner': 'alice'}
        identity = {'version': 1, 'owner': 'alice'}
        with (patch.object(reconcile_worker_result, '_fence_expected',
                           side_effect=ValueError('stale plan')),
              patch('modules.goal_tools.verify') as verify,
              patch('modules.runtime_worker_result.accept_and_commit') as commit):
            with self.assertRaisesRegex(ValueError, 'stale plan'):
                reconcile_worker_result.accept_and_commit(
                    output, identity, 'research', {'url': 'https://example.test'},
                )
        verify.assert_not_called()
        commit.assert_not_called()

    def test_effect_recovery_verifies_before_receipt_and_cas(self):
        output = {'state': 'done', 'receipt': {'service': 'gmail', 'remote_id': 'x'}}
        expected = {'owner': 'alice'}
        reader = Mock(return_value=output)
        with (patch.object(effect_recovery_runtime, '_checked', return_value=expected),
              patch.object(effect_recovery_runtime, '_journal', return_value=(Mock(), 'effect')),
              patch('modules.crash_recovery.decide', return_value={'state': 'unknown'}),
              patch('modules.goal_tools.verify', side_effect=ValueError('unverified')),
              patch.object(effect_recovery_runtime, 'record_receipt') as receipt,
              patch('modules.runtime_worker_result.accept_and_commit') as commit):
            with self.assertRaisesRegex(ValueError, 'unverified'):
                effect_recovery_runtime.reconcile(expected, reader)
        reader.assert_called_once_with()
        receipt.assert_not_called()
        commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
