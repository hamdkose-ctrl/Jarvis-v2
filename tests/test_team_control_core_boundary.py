"""Regression contract for moving team lifecycle authority out of the UI bridge."""
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import goal_executor as goals, llm, service_store, task_agents
from modules import team_control_service
from web_tasks import WebTasks


class TeamControlCoreBoundaryTests(unittest.TestCase):
    def test_ui_bridge_only_forwards_team_control_request(self):
        source = inspect.getsource(WebTasks.team_control)
        self.assertIn('team_control_service', source)
        for authority in ('goal_executor', 'task_agents', 'control_key', "job['state']", "job['tasks']"):
            self.assertNotIn(authority, source)

    def test_core_rejects_stale_goal_before_transport(self):
        profile = SimpleNamespace(slug='alice', name='Alice')
        submit = Mock(return_value=True)
        current = {'id':'b'*16, 'owner':'alice', 'state':'question', 'question':'Yeni?', 'outputs':{}, 'steps':[]}
        with patch.object(service_store, 'identity'), patch.object(goals, 'latest', return_value=current):
            with self.assertRaises(ValueError):
                team_control_service.dispatch(profile.slug, profile.name, submit, 'goal', 'a'*16, 'answer', 'stale', 'Yanıt')
        submit.assert_not_called()

    def test_core_rejects_changed_task_approval_before_transport(self):
        profile = SimpleNamespace(slug='alice', name='Alice')
        submit = Mock(return_value=True)
        job = {'id':'a'*12, 'owner':'alice', 'state':'approval',
               'tasks':[{'id':'s1','agent':'publish','state':'approval'}],
               'outputs':{'s1':{'state':'approval','id':'c'*16,'text':'Yeni işlem'}}}
        with patch.object(service_store, 'identity'), patch.object(task_agents, '_load', return_value=job):
            with self.assertRaises(ValueError):
                team_control_service.dispatch(profile.slug, profile.name, submit, 'task', job['id'], 'approve', goals.control_key(job), approval_id='b'*16)
        submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
