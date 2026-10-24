import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / 'scripts' / 'git_local_guard.py'
INSTALLER = ROOT / 'scripts' / 'install_git_hooks.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalGitGuardTests(unittest.TestCase):
    def test_main_and_master_are_protected_but_other_branch_names_are_allowed(self):
        guard = load(GUARD, 'git_local_guard')
        self.assertTrue(guard.protected_branch('main'))
        self.assertTrue(guard.protected_branch('master'))
        self.assertFalse(guard.protected_branch('gpt/local-guard'))
        self.assertFalse(guard.protected_branch('hotfix/acil'))

    def test_pre_push_rejects_direct_main_and_non_fast_forward_updates(self):
        guard = load(GUARD, 'git_local_guard_push')
        zero = '0' * 40
        old = '1' * 40
        new = '2' * 40
        lines = [
            f'refs/heads/work {new} refs/heads/main {old}',
            f'refs/heads/work {new} refs/heads/work {old}',
            f'refs/heads/new {new} refs/heads/new {zero}',
        ]
        violations = guard.push_violations(lines, is_ancestor=lambda a, b: False)
        self.assertTrue(any('main' in item for item in violations))
        self.assertTrue(any('non-fast-forward' in item for item in violations))
        self.assertFalse(any('refs/heads/new' in item for item in violations))

    def test_fast_forward_non_main_push_is_allowed(self):
        guard = load(GUARD, 'git_local_guard_ff')
        old = '1' * 40
        new = '2' * 40
        lines = [f'refs/heads/work {new} refs/heads/work {old}']
        self.assertEqual(guard.push_violations(lines, is_ancestor=lambda a, b: True), [])

    def test_installer_uses_repo_local_hooks_path_only(self):
        installer = load(INSTALLER, 'install_git_hooks')
        calls = []
        installer.configure_hooks(Path('C:/repo'), runner=lambda cmd, cwd: calls.append((cmd, cwd)))
        self.assertEqual(calls, [(['git', 'config', '--local', 'core.hooksPath', '.githooks'], Path('C:/repo'))])


if __name__ == '__main__':
    unittest.main()
