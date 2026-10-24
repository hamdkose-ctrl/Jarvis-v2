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

    # -- Alias hardening -------------------------------------------------

    def test_from_import_function_alias_direct_call_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_tools import execute as run_tool\n"
            "run_tool(runtime, 'publish', {}, {}, identity)\n"
        )
        self.assertIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_module_alias_attribute_call_is_blocker(self):
        report = self._scan_source(
            "import modules.goal_tools as tools\n"
            "tools.execute(runtime, 'publish', {}, {}, identity)\n"
        )
        self.assertIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_cas_function_alias_direct_call_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import compare_and_swap as cas\n"
            "cas(path, expected_version=1, next_state={})\n"
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})

    def test_gate_module_alias_attribute_call_without_context_is_blocker(self):
        report = self._scan_source(
            "import modules.runtime_execution_gate as gate\n"
            "gate.plan_task('coder', {}, approval_verified=False)\n"
        )
        self.assertIn('ARCH-002', {row['rule'] for row in report['blockers']})

    def test_gate_module_alias_attribute_call_with_explicit_context_is_clean(self):
        report = self._scan_source(
            "import modules.runtime_execution_gate as gate\n"
            "gate.plan_task(\n"
            "    'coder', {}, approval_verified=False,\n"
            "    domain_invariant=1, domain_authority=2, user_authority=3,\n"
            "    job_authority=4, effect_state=5,\n"
            ")\n"
        )
        self.assertNotIn('ARCH-002', {row['rule'] for row in report['blockers']})

    def test_cas_alias_inside_allowlisted_adapter_is_not_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import compare_and_swap as cas\n"
            "cas(path, expected_version=1, next_state={})\n",
            name='goal_state_compat.py',
        )
        self.assertNotIn('ARCH-001', {row['rule'] for row in report['blockers']})

    def test_execute_alias_inside_allowlisted_caller_is_not_blocker(self):
        report = self._scan_source(
            "import modules.goal_tools as tools\n"
            "tools.execute(runtime, 'publish', {}, {}, identity)\n",
            name='worker_result_hook.py',
        )
        self.assertNotIn('ARCH-003', {row['rule'] for row in report['blockers']})

    def test_direct_call_rules_still_detected_without_alias(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n"
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})

    # -- Canonical GoalState storage writer allowlists ---------------------

    def test_direct_goalstate_create_outside_compat_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.create(path, {'goal_id': 'g1'})\n"
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_create_function_alias_outside_compat_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import create as make\n"
            "make(path, {'goal_id': 'g1'})\n"
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_create_module_alias_outside_compat_is_blocker(self):
        report = self._scan_source(
            "import modules.goal_state_store as store\n"
            "store.create(path, {'goal_id': 'g1'})\n"
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_create_inside_compat_adapter_is_clean(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.create(path, {'goal_id': 'g1'})\n",
            name='goal_state_compat.py',
        )
        self.assertNotIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_direct_goalstate_compensate_outside_save_hook_is_blocker(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compensate(path, previous_state={}, new_state={})\n"
        )
        self.assertIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_compensate_module_alias_outside_save_hook_is_blocker(self):
        report = self._scan_source(
            "import modules.goal_state_store as store\n"
            "store.compensate(path, previous_state={}, new_state={})\n"
        )
        self.assertIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_compensate_function_alias_outside_save_hook_is_blocker(self):
        report = self._scan_source(
            "from modules.goal_state_store import compensate as undo\n"
            "undo(path, previous_state={}, new_state={})\n"
        )
        self.assertIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_compensate_inside_save_hook_is_clean(self):
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compensate(path, previous_state={}, new_state={})\n",
            name='goal_state_save_hook.py',
        )
        self.assertNotIn('ARCH-005', {row['rule'] for row in report['blockers']})

    def test_writer_allowlists_are_not_cross_permission(self):
        # Being inside the CAS adapter set does not authorize create().
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.create(path, {'goal_id': 'g1'})\n",
            name='worker_result_commit.py',
        )
        self.assertIn('ARCH-004', {row['rule'] for row in report['blockers']})

    def test_cas_allowlist_behavior_is_unchanged(self):
        for name in ('worker_result_commit.py', 'runtime_event_commit.py'):
            report = self._scan_source(
                "from modules import goal_state_store\n"
                "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n",
                name=name,
            )
            self.assertNotIn('ARCH-001', {row['rule'] for row in report['blockers']}, name)
        report = self._scan_source(
            "from modules import goal_state_store\n"
            "goal_state_store.compare_and_swap(path, expected_version=1, next_state={})\n",
            name='goal_state_save_hook.py',
        )
        self.assertIn('ARCH-001', {row['rule'] for row in report['blockers']})


if __name__ == '__main__':
    unittest.main()
