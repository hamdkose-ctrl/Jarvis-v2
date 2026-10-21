import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / 'pc_test_loop.py'
SPEC = importlib.util.spec_from_file_location('pc_test_loop', MODULE_PATH)
loop = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(loop)


class PcTestLoopTests(unittest.TestCase):
    def test_news_final_pass_is_required_before_completion(self):
        base = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'a'*40, 'status': 'passed'}
        news = {'exit_code': 1, 'tail': 'fail', 'checks': [{'check': 'news_chat_resume', 'state': 'failed'}]}
        with mock.patch.object(loop.watcher, 'add_worktree'), \
                mock.patch.object(loop.watcher, 'remove_worktree'), \
                mock.patch.object(loop.watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(loop.watcher, 'run_acceptance', return_value=news):
            result = loop.run_news_final(Path('repo'), dict(base))
        self.assertEqual(result['status'], 'failed')

    def test_repeated_same_failure_stops_extra_terra_call(self):
        report = {'sha': 'b'*40, 'status': 'failed', 'desktop_acceptance': {'exit_code': 1, 'tail': 'same failure'}}
        signature = loop.failure_signature(report)
        run_it, reason = loop.should_run_codex(report, {
            'sha': 'other',
            'last_failure_signature': signature,
            'result': {'state': 'failed'},
        })
        self.assertFalse(run_it)
        self.assertEqual(reason, 'repeated_failure_stopped')

    def test_quota_state_retries_same_sha_after_deadline(self):
        report = {'sha': 'c'*40, 'status': 'failed', 'desktop_acceptance': {'exit_code': 1, 'tail': 'real failure'}}
        state = {
            'sha': report['sha'],
            'retry_after': 200.0,
            'result': {'state': 'pending_quota'},
        }
        run_it, reason = loop.should_run_codex(report, state, now=199.0)
        self.assertFalse(run_it)
        self.assertEqual(reason, 'quota_wait')
        run_it, reason = loop.should_run_codex(report, state, now=200.0)
        self.assertTrue(run_it)
        self.assertEqual(reason, 'quota_retry')

    def test_pending_quota_state_does_not_store_failure_signature(self):
        report = {'sha': 'd'*40, 'status': 'failed', 'desktop_acceptance': {'exit_code': 1, 'tail': 'same failure'}}
        with mock.patch.object(loop.time, 'time', return_value=100.0):
            state = loop.next_state(report, {'state': 'pending_quota', 'reason': 'quota_or_rate_limit'})
        self.assertEqual(state['retry_after'], 100.0 + loop.QUOTA_RETRY_SECONDS)
        self.assertNotIn('last_failure_signature', state)


if __name__ == '__main__':
    unittest.main()
