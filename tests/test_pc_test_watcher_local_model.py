import importlib.util
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'pc_test_watcher.py'
SPEC = importlib.util.spec_from_file_location('pc_test_watcher_local_model', MODULE_PATH)
watcher = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(watcher)


class PcWatcherLocalModelAcceptanceTests(unittest.TestCase):
    def test_model_ui_changes_select_feature_specific_acceptance_only(self):
        scope = watcher.acceptance_scope([
            'modules/llm.py',
            'web_models.py',
            'webui/ui-refresh.js',
            'tests/test_ollama_model_autoselect.py',
            'tests/ai_page_behavior.js',
        ])
        self.assertTrue(scope['local_model'])
        self.assertFalse(scope['desktop'])
        self.assertFalse(scope['news'])

    def test_local_model_acceptance_is_required_for_suite_pass(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        failed = {'exit_code': 1, 'tail': 'feature failed', 'result': {'state': 'failed'}}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_local_model_acceptance', return_value=failed):
            result = watcher.run_suite(
                Path('repo'), Path('worktree'), 'ref', 'a' * 40,
                desktop=False, news=False, local_model=True,
            )
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['local_model_acceptance']['result']['state'], 'failed')

    def test_comment_names_exact_head_local_model_gate(self):
        report = {
            'sha': 'd' * 40,
            'status': 'passed',
            'validation': {'exit_code': 0, 'tail': 'ok'},
            'local_model_acceptance': {
                'exit_code': 0,
                'tail': 'ok',
                'result': {'state': 'passed', 'detail': 'production_render=passed; inference=passed'},
            },
        }
        body = watcher.pr_comment_body(report)
        self.assertIn('Yerel model UI/inference: **passed**', body)
        self.assertIn('dddddddddddd', body)


if __name__ == '__main__':
    unittest.main()
