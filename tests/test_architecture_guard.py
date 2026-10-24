import tempfile
import unittest
from pathlib import Path


class ArchitectureGuardTests(unittest.TestCase):
    def setUp(self):
        from modules import architecture_guard
        self.guard = architecture_guard

    def _scan_source(self, source: str, name='rogue.py'):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            modules = root / 'modules'
            modules.mkdir()
            (modules / name).write_text(source, encoding='utf-8')
            return self.guard.scan(root)

    def test_current_repository_has_no_stage_0_4_blockers(self):
        root = Path(__file__).resolve().parents[1]
        report = self.guard.scan(root)
        self.assertEqual(report['blockers'], [], report)
        self.assertEqual(report['scope'], 'stage-0-4')

    def test_direct_goalstate_cas_outside_canonical_adapters_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n"
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})

    def test_durable_plan_task_requires_explicit_decision_context(self):
        report = self._scan_source(
            "from modules import runtime_execution_gate\n"
            "runtime_execution_gate.plan_task('coder', {}, approval_verified=False)\n"
        )
        self.assertIn('ARCH-002', {row['rule'] for row in report['blockers']})

    def test_new_direct_goal_tools_executor_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_tools\n"
            "goal_tools.execute(runtime, 'publish', {}, {}, identity)\n"
        )
        self.assertIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_runtime_event_subscription_gap_is_warning_not_blocker(self):
        report = self._scan_source("x = 1\n")
        self.assertIn('ARCH-W001', {row['rule'] for row in report['warnings']})
        self.assertNotIn('ARCH-W001', {row['rule'] for row in report['blockers']})


if __name__ == '__main__':
    unittest.main()
