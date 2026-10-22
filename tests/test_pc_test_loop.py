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
    def test_news_branch_uses_news_focus_first(self):
        profile = loop.focus_profile('refs/remotes/origin/gpt/rss-news-receipts')
        self.assertEqual(profile, ('news', '--news', 'news_chat_resume'))

    def test_mail_branch_uses_mail_focus_first(self):
        profile = loop.focus_profile('refs/remotes/origin/gpt/gmail-attachment-fix')
        self.assertEqual(profile, ('gmail', '--gmail', 'gmail_attachment'))

    def test_unknown_branch_falls_back_to_full_validation(self):
        self.assertIsNone(loop.focus_profile('refs/remotes/origin/gpt/parser-cleanup'))

    def test_focus_gate_failure_does_not_claim_pass(self):
        target = {'ref': 'refs/remotes/origin/gpt/rss-news-receipts', 'sha': 'a'*40}
        failed = {'exit_code': 1, 'tail': 'news failed', 'checks': [{'check': 'news_chat_resume', 'state': 'failed'}]}
        with mock.patch.object(loop.watcher, 'add_worktree'), \
                mock.patch.object(loop.watcher, 'remove_worktree'), \
                mock.patch.object(loop.watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(loop.watcher, 'run_acceptance', return_value=failed):
            result = loop.run_focus_gate(Path('repo'), target, ('news', '--news', 'news_chat_resume'))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['focus_profile'], 'news')

    def test_focus_gate_passes_only_expected_check(self):
        target = {'ref': 'refs/remotes/origin/gpt/rss-news-receipts', 'sha': 'a'*40}
        passed = {'exit_code': 0, 'tail': '', 'checks': [{'check': 'news_chat_resume', 'state': 'passed'}]}
        with mock.patch.object(loop.watcher, 'add_worktree'), \
                mock.patch.object(loop.watcher, 'remove_worktree'), \
                mock.patch.object(loop.watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(loop.watcher, 'run_acceptance', return_value=passed):
            result = loop.run_focus_gate(Path('repo'), target, ('news', '--news', 'news_chat_resume'))
        self.assertEqual(result['status'], 'focus_passed')

    def test_passed_report_never_calls_terra(self):
        report = {'sha': 'a'*40, 'status': 'passed'}
        run_it, reason = loop.should_run_codex(report, {'sha': 'other'})
        self.assertFalse(run_it)
        self.assertEqual(reason, 'already_passed')

    def test_focus_passed_report_never_calls_terra(self):
        report = {'sha': 'a'*40, 'status': 'focus_passed'}
        run_it, reason = loop.should_run_codex(report, {'sha': 'other'})
        self.assertFalse(run_it)
        self.assertEqual(reason, 'already_passed')

    def test_same_sha_is_not_sent_to_terra_twice(self):
        report = {'sha': 'b'*40, 'status': 'failed', 'desktop_acceptance': {'exit_code': 1, 'tail': 'same failure'}}
        run_it, reason = loop.should_run_codex(report, {
            'sha': report['sha'],
            'last_failure_signature': loop.failure_signature(report),
            'result': {'state': 'failed'},
        })
        self.assertFalse(run_it)
        self.assertEqual(reason, 'same_sha_already_handled')

    def test_new_sha_retries_even_when_failure_signature_is_same(self):
        report = {'sha': 'c'*40, 'status': 'failed', 'desktop_acceptance': {'exit_code': 1, 'tail': 'same failure'}}
        signature = loop.failure_signature(report)
        run_it, reason = loop.should_run_codex(report, {
            'sha': 'b'*40,
            'last_failure_signature': signature,
            'result': {'state': 'failed'},
        })
        self.assertTrue(run_it)
        self.assertEqual(reason, 'new_result')

    def test_quota_state_retries_same_sha_after_deadline(self):
        report = {'sha': 'd'*40, 'status': 'failed', 'desktop_acceptance': {'exit_code': 1, 'tail': 'real failure'}}
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
        report = {'sha': 'e'*40, 'status': 'failed', 'desktop_acceptance': {'exit_code': 1, 'tail': 'same failure'}}
        with mock.patch.object(loop.time, 'time', return_value=100.0):
            state = loop.next_state(report, {'state': 'pending_quota', 'reason': 'quota_or_rate_limit'})
        self.assertEqual(state['retry_after'], 100.0 + loop.QUOTA_RETRY_SECONDS)
        self.assertNotIn('last_failure_signature', state)


if __name__ == '__main__':
    unittest.main()
