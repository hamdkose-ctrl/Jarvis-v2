"""Regression boundary for moving team verification authority out of the UI bridge."""
import inspect
import unittest
from unittest.mock import patch

from modules import service_store, task_agents, task_results, team_verify_service
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

    def test_core_task_verification_checks_only_done_outputs(self):
        done = {'state': 'done', 'file': 'evidence.txt'}
        waiting = {'state': 'waiting'}
        job = {'outputs': {'done-step': done, 'waiting-step': waiting}}
        with (
            patch.object(service_store, 'identity'),
            patch.object(task_agents, '_load', return_value=job),
            patch.object(task_results, 'verify') as verifier,
        ):
            result = team_verify_service.verify('alice', 'task', 'a' * 12)

        verifier.assert_called_once_with(done, owner='alice')
        self.assertEqual(result['checked'], 1)
        self.assertEqual(result['failed'], [])
        self.assertTrue(result['ok'])


if __name__ == '__main__':
    unittest.main()
