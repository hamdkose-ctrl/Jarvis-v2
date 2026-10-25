import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import goal_tools


class DesktopWindowObserveTests(unittest.TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(
            profile=SimpleNamespace(slug='alice'),
            pc_profile=lambda: SimpleNamespace(slug='alice'),
            _cur_source='yazı',
        )
        self.identity = {'owner': 'alice', 'job_id': 'job-1', 'task_id': 'step-1'}
        self.data = {'kind': 'window', 'target': 'Notepad', 'question': 'Açık belgeyi özetle'}

    def test_window_observation_is_a_read_only_goal_input(self):
        self.assertEqual(goal_tools.validate('observe', self.data), self.data)
        with self.assertRaises(ValueError):
            goal_tools.validate('observe', {'kind': 'window', 'question': 'İncele'})
        with self.assertRaises(ValueError):
            goal_tools.validate('observe', {'kind': 'screen', 'target': 'Notepad', 'question': 'İncele'})

    def test_window_observation_uses_existing_desktop_read_only_mode_only(self):
        from modules import system_control
        observed = {
            'state': 'done', 'read_only': True,
            'observation': {'window': {'app': 'notepad', 'title': 'Adsız - Not Defteri'}, 'controls': []},
        }
        with patch('modules.desktop_agent.run', return_value=observed) as run, \
             patch('modules.desktop_agent.handle') as handle, \
             patch.object(system_control, 'open_application') as open_application:
            output = goal_tools.execute(self.runtime, 'observe', self.data, {}, self.identity)
        self.assertEqual(output['state'], 'done')
        self.assertEqual(output['local_evidence'], 'observe')
        self.assertEqual(output['window_observation'], observed['observation'])
        job = run.call_args.args[0]
        self.assertEqual(job['owner'], 'alice')
        self.assertEqual(job['target'], 'Notepad')
        self.assertEqual(job['history'], [])
        self.assertTrue(run.call_args.kwargs['read_only'])
        handle.assert_not_called()
        open_application.assert_not_called()

    def test_missing_or_refused_window_is_not_reported_as_observed(self):
        blocked = {'state': 'blocked', 'read_only': True, 'reason_code': 'WINDOW_MISSING',
                   'message': 'Salt-okunur gözlem için hedef pencere açık değil.'}
        with patch('modules.desktop_agent.run', return_value=blocked):
            with self.assertRaises(goal_tools.NotStarted):
                goal_tools.execute(self.runtime, 'observe', self.data, {}, self.identity)


if __name__ == '__main__':
    unittest.main()
