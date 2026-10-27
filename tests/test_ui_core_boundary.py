import tempfile
import unittest
from pathlib import Path


class UiCoreBoundaryGuardTests(unittest.TestCase):
    def setUp(self):
        from modules import architecture_guard
        self.guard = architecture_guard

    def _scan_ui(self, source: str, name: str = 'web_new_feature.py'):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'modules').mkdir()
            (root / name).write_text(source, encoding='utf-8')
            return self.guard.scan(root)

    def test_new_ui_dependency_on_business_authority_is_blocker(self):
        report = self._scan_ui(
            "from modules import goal_executor\n"
            "def approve(job_id):\n"
            "    return goal_executor.cancel_job('owner', job_id)\n"
        )
        self.assertIn('ARCH-006', {row['rule'] for row in report['blockers']})

    def test_ui_authority_alias_import_is_also_blocker(self):
        report = self._scan_ui(
            "import modules.goal_state_store as state_store\n"
            "def render():\n"
            "    return state_store\n"
        )
        self.assertIn('ARCH-006', {row['rule'] for row in report['blockers']})

    def test_known_web_tasks_debt_is_baselined_not_blocker(self):
        report = self._scan_ui(
            "from modules import goal_executor, goal_tools, task_agents, task_results\n",
            name='web_tasks.py',
        )
        self.assertNotIn('ARCH-006', {row['rule'] for row in report['blockers']})
        self.assertIn('ARCH-W003', {row['rule'] for row in report['warnings']})

    def test_presentation_dependency_is_not_business_authority(self):
        report = self._scan_ui(
            "from modules import ui_jobs\n"
            "def status(owner, rid):\n"
            "    return ui_jobs.status(owner, rid)\n"
        )
        self.assertNotIn('ARCH-006', {row['rule'] for row in report['blockers']})


if __name__ == '__main__':
    unittest.main()
