import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'pc_test_watcher.py'
SPEC = importlib.util.spec_from_file_location('pc_test_watcher', MODULE_PATH)
watcher = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(watcher)


class PcTestWatcherTests(unittest.TestCase):
    def test_default_pattern_covers_nested_remote_refs_with_real_git(self):
        """The namespace root must include slash-containing remote branch names."""
        self.assertEqual(watcher.DEFAULT_PATTERN, 'refs/remotes/origin')
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(['git', 'init', '--quiet'], cwd=repo, check=True)
            blob = subprocess.check_output(
                ['git', 'hash-object', '-w', '--stdin'], cwd=repo, input=b'nested-ref-test\n'
            ).decode().strip()
            subprocess.run(
                ['git', 'update-ref', 'refs/remotes/origin/claude/jarvisbench-v0', blob],
                cwd=repo, check=True,
            )
            refs = subprocess.check_output(
                ['git', 'for-each-ref', '--format=%(refname)', watcher.DEFAULT_PATTERN],
                cwd=repo, text=True,
            ).splitlines()
        self.assertIn('refs/remotes/origin/claude/jarvisbench-v0', refs)

    def test_batch_does_not_force_news_acceptance(self):
        batch = (MODULE_PATH.parents[0] / 'pc_test_watcher.bat').read_text(encoding='utf-8')
        self.assertNotIn('pc_test_watcher.py --news', batch)

    def test_acceptance_scope_keeps_docs_and_hook_changes_validation_only(self):
        scope = watcher.acceptance_scope([
            'docs/PC_TEST_WATCHER.md',
            '.githooks/pre-push',
            'scripts/git_hooks_kur.bat',
        ])
        self.assertFalse(scope['desktop'])
        self.assertFalse(scope['news'])

    def test_acceptance_scope_selects_desktop_runtime_changes(self):
        scope = watcher.acceptance_scope([
            'modules/desktop_uia.py',
            'tests/test_desktop_agent.py',
        ])
        self.assertTrue(scope['desktop'])
        self.assertFalse(scope['news'])

    def test_acceptance_scope_selects_news_runtime_changes(self):
        scope = watcher.acceptance_scope([
            'modules/news_recovery.py',
            'tests/test_news_recovery_catalog.py',
        ])
        self.assertFalse(scope['desktop'])
        self.assertTrue(scope['news'])

    def test_acceptance_scope_selects_both_for_shared_acceptance_runtime(self):
        scope = watcher.acceptance_scope(['modules/acceptance_checks.py'])
        self.assertTrue(scope['desktop'])
        self.assertTrue(scope['news'])

    def test_acceptance_scope_manual_flags_override_path_scope(self):
        scope = watcher.acceptance_scope(['docs/architecture/example.md'], desktop=True, news=True)
        self.assertTrue(scope['desktop'])
        self.assertTrue(scope['news'])

    def test_choose_candidate_skips_resolved_sha(self):
        candidates = [
            {'ref': 'refs/remotes/origin/gpt/new', 'sha': 'bbb', 'time': 2},
            {'ref': 'refs/remotes/origin/gpt/old', 'sha': 'aaa', 'time': 1},
        ]
        seen = {
            'refs/remotes/origin/gpt/new': {
                'sha': 'bbb', 'status': 'passed', 'last_attempt': 100.0
            }
        }
        self.assertEqual(watcher.choose_candidate(candidates, seen, now=200.0), candidates[1])

    def test_legacy_seen_sha_is_rechecked_once(self):
        candidate = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'abc', 'time': 1}
        seen = {candidate['ref']: candidate['sha']}
        self.assertEqual(watcher.choose_candidate([candidate], seen, now=1000.0), candidate)

    def test_unresolved_same_sha_is_not_automatically_retried(self):
        candidate = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'abc', 'time': 1}
        seen = {
            candidate['ref']: {
                'sha': 'abc', 'status': 'pending_retry', 'last_attempt': 100.0
            }
        }
        self.assertIsNone(watcher.choose_candidate([candidate], seen, now=1000.0))

    def test_open_pr_refs_returns_only_open_branch_refs(self):
        listed = mock.Mock(returncode=0, stdout='[{"headRefName":"gpt/current"},{"headRefName":"feature/not-watched"}]')
        with mock.patch.object(watcher, 'gh_exe', return_value='gh'), \
                mock.patch.object(watcher, 'run', return_value=listed) as run:
            refs = watcher.open_pr_refs(Path('repo'))
        self.assertEqual(refs, {
            'refs/remotes/origin/gpt/current',
            'refs/remotes/origin/feature/not-watched',
        })
        self.assertEqual(run.call_args.args[0][:5], ['gh', 'pr', 'list', '--state', 'open'])

    def test_open_pr_refs_fails_closed_without_github_cli(self):
        with mock.patch.object(watcher, 'gh_exe', return_value=None):
            self.assertIsNone(watcher.open_pr_refs(Path('repo')))

    def test_once_considers_only_open_pr_heads(self):
        open_item = {'ref': 'refs/remotes/origin/gpt/open', 'sha': 'open', 'time': 2}
        closed_item = {'ref': 'refs/remotes/origin/gpt/closed', 'sha': 'closed', 'time': 1}
        with mock.patch.object(watcher, 'load_state', return_value={'seen': {}}), \
                mock.patch.object(watcher, 'remote_heads', return_value=[open_item, closed_item]), \
                mock.patch.object(watcher, 'open_pr_refs', return_value={open_item['ref']}), \
                mock.patch.object(watcher, 'choose_candidate', return_value=None) as choose:
            changed = watcher.once(Path('repo'), Path('state.json'), Path('report.json'), 'refs/remotes/origin/gpt/*', desktop=True, news=False)
        self.assertFalse(changed)
        self.assertEqual(choose.call_args.args[0], [open_item])

    def test_once_runs_validation_only_for_docs_scope(self):
        item = {'ref': 'refs/remotes/origin/gpt/docs', 'sha': 'a' * 40, 'time': 2}
        result = {'status': 'passed', 'validation': {'exit_code': 0, 'tail': 'OK'}}
        with mock.patch.object(watcher, 'load_state', return_value={'seen': {}}), \
                mock.patch.object(watcher, 'remote_heads', return_value=[item]), \
                mock.patch.object(watcher, 'open_pr_refs', return_value={item['ref']}), \
                mock.patch.object(watcher, 'changed_paths', return_value=['docs/architecture/guide.md']), \
                mock.patch.object(watcher, 'add_worktree'), \
                mock.patch.object(watcher, 'remove_worktree'), \
                mock.patch.object(watcher, 'run_suite', return_value=result) as suite, \
                mock.patch.object(watcher, 'publish_pr_comment', return_value={'state': 'skipped'}), \
                mock.patch.object(watcher, 'save_json'):
            changed = watcher.once(Path('repo'), Path('state.json'), Path('report.json'), 'refs/remotes/origin/gpt/*', desktop=False, news=False)
        self.assertTrue(changed)
        self.assertFalse(suite.call_args.kwargs['desktop'])
        self.assertFalse(suite.call_args.kwargs['news'])

    def test_new_sha_runs_even_if_previous_sha_passed(self):
        candidate = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'new', 'time': 2}
        seen = {
            candidate['ref']: {
                'sha': 'old', 'status': 'passed', 'last_attempt': 100.0
            }
        }
        self.assertEqual(watcher.choose_candidate([candidate], seen, now=101.0), candidate)

    def test_suite_reports_missing_venv_without_running_another_python(self):
        with mock.patch.object(watcher, 'python_exe', return_value=None), \
                mock.patch.object(watcher, 'run') as run:
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=False)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['validation']['exit_code'], 2)
        self.assertIn('.venv\\Scripts\\python.exe', result['validation']['tail'])
        run.assert_not_called()

    def test_existing_worktree_is_git_removed_before_filesystem_cleanup(self):
        root = Path('repo'); target = Path('existing-worktree')
        with mock.patch.object(watcher.Path, 'exists', return_value=True), \
                mock.patch.object(watcher, 'remove_worktree') as remove, \
                mock.patch.object(watcher, 'run') as run:
            watcher.add_worktree(root, 'a'*40, target)
        remove.assert_called_once_with(root, target)
        self.assertEqual(run.call_args_list[-1].args[0][:3], ['git', 'worktree', 'add'])

    def test_normal_suite_does_not_run_news(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': '', 'checks': [{'check': 'calculator', 'state': 'passed'}]}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', return_value=desktop) as acceptance:
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=False)
        self.assertEqual(result['status'], 'passed')
        acceptance.assert_called_once_with(Path('python.exe'), Path('worktree'), '--desktop')
        self.assertNotIn('news_acceptance', result)

    def test_news_is_separate_final_gate(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': '', 'checks': [{'check': 'calculator', 'state': 'passed'}]}
        news = {'exit_code': 1, 'tail': 'news failed', 'checks': [{'check': 'news_chat_resume', 'state': 'failed'}]}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', side_effect=[desktop, news]):
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['news_acceptance']['exit_code'], 1)

    def test_validation_failure_never_starts_desktop_or_news_acceptance(self):
        validation = mock.Mock(returncode=1, stdout='validation failed')
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance') as acceptance:
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=True)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('desktop_acceptance', result)
        self.assertNotIn('news_acceptance', result)
        acceptance.assert_not_called()

    def test_desktop_exit_zero_without_calculator_evidence_fails_suite(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': 'incomplete', 'checks': []}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', return_value=desktop):
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=False)
        self.assertEqual(result['status'], 'failed')

    def test_news_exit_zero_without_required_evidence_fails_suite_and_comment(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': '', 'checks': [{'check':'calculator', 'state':'passed'}]}
        news = {'exit_code': 0, 'tail': 'incomplete', 'checks': []}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', side_effect=[desktop, news]):
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=True)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Haber: **failed**', watcher.pr_comment_body(result))

    def test_pr_comment_reports_only_blocks_that_ran(self):
        report = {
            'sha': 'b' * 40,
            'status': 'failed',
            'validation': {'exit_code': 1, 'tail': 'traceback'},
            'desktop_acceptance': {'exit_code': 0, 'tail': 'ok', 'checks': [{'check':'calculator','state':'passed'}]},
        }
        body = watcher.pr_comment_body(report)
        self.assertIn('Validation: **failed**', body)
        self.assertIn('Desktop: **passed**', body)
        self.assertNotIn('Haber', body)
        self.assertNotIn('traceback', body)

    def test_pr_comment_does_not_call_desktop_passed_without_calculator_evidence(self):
        report = {
            'sha': 'c' * 40,
            'status': 'failed',
            'validation': {'exit_code': 0, 'tail': 'ok'},
            'desktop_acceptance': {'exit_code': 0, 'tail': 'ok', 'checks': []},
        }
        self.assertIn('Desktop: **failed**', watcher.pr_comment_body(report))


    def test_existing_pr_comment_is_not_posted_twice_during_recovery(self):
        sha = "b" * 40
        ref = "refs/remotes/origin/gpt/one"
        comment = watcher.pr_comment_body({"sha": sha, "status": "passed"})
        found = mock.Mock(returncode=0, stdout='[{"number":537,"url":"https://github.com/x/y/pull/537"}]')
        existing = mock.Mock(returncode=0, stdout=__import__("json").dumps(
            {"comments": [{"body": comment}]}))
        with mock.patch.object(watcher, "gh_exe", return_value="gh"), \
                mock.patch.object(watcher, "run", side_effect=[found, existing]) as run:
            result = watcher.publish_pr_comment(Path("repo"), ref,
                {"sha": sha, "status": "passed"}, verify_existing=True)
        self.assertEqual(result["state"], "published")
        self.assertTrue(result["already_present"])
        self.assertEqual(run.call_count, 2)

    def test_reconcile_publishes_archived_sha_without_rerunning_suite(self):
        sha = "a" * 40
        ref = "refs/remotes/origin/gpt/test"
        item = {"sha": sha, "ref": ref, "time": 100}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report_path, state_path = folder / "last.json", folder / "state.json"
            report = {"sha": sha, "ref": ref, "started": 1, "status": "passed",
                      "validation": {"exit_code": 0},
                      "github_pr_comment": {"state": "failed", "reason": "gh_pr_comment_failed"}}
            watcher.archive_report(report_path, report)
            watcher.save_json(report_path, report)
            seen = {ref: {"sha": sha, "status": "passed"}}
            with mock.patch.object(watcher, "publish_pr_comment",
                                   return_value={"state": "published", "pr": 537}) as publish, \
                 mock.patch.object(watcher, "run_suite",
                                   side_effect=AssertionError("a completed suite must never rerun")):
                self.assertTrue(watcher.reconcile_archived_reports(
                    Path("repo"), state_path, report_path, [item], seen, now=100))
            publish.assert_called_once()
            self.assertTrue(publish.call_args.kwargs["verify_existing"])
            self.assertEqual(watcher.load_state(report_path)["github_pr_comment"]["state"], "published")
            self.assertEqual(watcher._archived_candidate_report(report_path, item)
                             ["github_pr_comment"]["state"], "published")
            with mock.patch.object(watcher, "publish_pr_comment") as second:
                self.assertFalse(watcher.reconcile_archived_reports(
                    Path("repo"), state_path, report_path, [item], seen, now=1000))
            second.assert_not_called()

    def test_recover_archived_report_after_crash_before_seen_file_write(self):
        sha = "c" * 40
        ref = "refs/remotes/origin/codex/feature"
        item = {"sha": sha, "ref": ref, "time": 100}
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "last.json"
            state_path = Path(tmp) / "state.json"
            watcher.archive_report(report_path, {
                "sha": sha, "ref": ref, "status": "failed", "started": 4,
                "validation": {"exit_code": 1}, "github_pr_comment": {"state": "published"}})
            seen = {}
            with mock.patch.object(watcher, "publish_pr_comment") as publish:
                self.assertTrue(watcher.reconcile_archived_reports(
                    Path("repo"), state_path, report_path, [item], seen, now=200))
            publish.assert_not_called()
            self.assertIsNone(watcher.choose_candidate([item], seen))
            self.assertEqual(watcher.load_state(state_path)["seen"][ref]["sha"], sha)

    def test_failed_publication_is_throttled_and_does_not_rerun_validation(self):
        sha = "d" * 40
        ref = "refs/remotes/origin/gpt/feature"
        item = {"sha": sha, "ref": ref, "time": 100}
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "last.json"
            state_path = Path(tmp) / "state.json"
            watcher.archive_report(report_path, {
                "sha": sha, "ref": ref, "status": "passed",
                "validation": {"exit_code": 0}})
            seen = {ref: {"sha": sha, "status": "passed"}}
            with mock.patch.object(watcher, "publish_pr_comment",
                                   return_value={"state": "failed", "reason": "network"}) as pub:
                self.assertTrue(watcher.reconcile_archived_reports(
                    Path("repo"), state_path, report_path, [item], seen, now=100))
                self.assertFalse(watcher.reconcile_archived_reports(
                    Path("repo"), state_path, report_path, [item], seen, now=150))
                self.assertTrue(watcher.reconcile_archived_reports(
                    Path("repo"), state_path, report_path, [item], seen, now=401))
            self.assertEqual(pub.call_count, 2)

    def test_invalid_or_foreign_archived_report_never_suppresses_validation(self):
        sha = "e" * 40
        ref = "refs/remotes/origin/gpt/correct"
        item = {"sha": sha, "ref": ref, "time": 10}
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "last.json"
            watcher.archive_report(report_path, {
                "sha": sha, "ref": "refs/remotes/origin/gpt/other",
                "status": "passed", "validation": {"exit_code": 0}})
            self.assertIsNone(watcher._archived_candidate_report(report_path, item))
            seen = {}
            with mock.patch.object(watcher, "publish_pr_comment") as publish:
                self.assertFalse(watcher.reconcile_archived_reports(
                    Path("repo"), Path(tmp) / "state.json", report_path,
                    [item], seen, now=11))
            publish.assert_not_called()
            self.assertEqual(watcher.choose_candidate([item], seen), item)

    def test_queue_status_distinguishes_no_report_from_unpublished_or_missing_ref(self):
        s1, s2 = "f"*40, "a"*40
        refs = ["refs/remotes/origin/gpt/ready", "refs/remotes/origin/gpt/unfinished",
                "refs/remotes/origin/codex/missing"]
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "last.json"
            state_path = Path(tmp) / "state.json"
            watcher.archive_report(report_path, {
                "sha": s1, "ref": refs[0], "status": "passed",
                "validation": {"exit_code": 0},
                "github_pr_comment": {"state": "skipped", "reason": "gh_cli_missing"}})
            watcher.save_json(state_path, {"seen": {
                refs[0]: {"sha": s1, "status": "passed"}}})
            remote = [{"ref": refs[0], "sha": s1, "time": 100},
                      {"ref": refs[1], "sha": s2, "time": 99}]
            with mock.patch.object(watcher, "open_pr_refs", return_value=set(refs)), \
                    mock.patch.object(watcher, "remote_heads", return_value=remote):
                data = watcher.queue_status(Path("repo"), state_path, report_path,
                                            watcher.DEFAULT_PATTERN)
            self.assertEqual({row["branch"]: row["state"] for row in data["branches"]}, {
                "gpt/ready": "report_not_published",
                "gpt/unfinished": "awaiting_test",
                "codex/missing": "remote_ref_missing",
            })


if __name__ == '__main__':
    unittest.main()
