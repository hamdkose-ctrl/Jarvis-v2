"""Regression boundary for moving team verification authority out of the UI bridge."""
import inspect
import unittest

from web_tasks import WebTasks


class TeamVerifyCoreBoundaryTests(unittest.TestCase):
    def test_ui_bridge_only_forwards_team_verify_request(self):
        source = inspect.getsource(WebTasks.team_verify)
        self.assertIn('team_verify_service', source)
        for authority in (
            'goal_executor', 'goal_tools', 'task_agents', 'task_results',
            'execution_record', "job.get('outputs'", "value.get('state')",
        ):
            self.assertNotIn(authority, source)


if __name__ == '__main__':
    unittest.main()
