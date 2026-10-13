import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from modules import task_tools as tools, task_agents as agents, browser_agent


class ToolContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for module, name in ((agents, 'tasks'), (browser_agent, 'browser')):
            p = patch.object(module, 'STORE', Path(self.tmp.name) / name)
            p.start()
            self.addCleanup(p.stop)

    def test_invalid_inputs_do_not_call_worker(self):
        cases = [('research', {}), ('research', {'url': 'file:///secret'}),
                 ('browser', {'url': 'https://example.com', 'instruction': False}),
                 ('writer', {'instruction': 'write', 'filename': '../secret.md'}),
                 ('coder', {'request': 'fix', 'owner': 'bob'}),
                 ('verify', {'approval': True})]
        with patch.object(agents, '_worker') as work:
            for kind, data in cases:
                with self.subTest(kind=kind, data=data), self.assertRaises(ValueError):
                    agents.worker('alice', {'agent': kind, 'input': data}, {})
            work.assert_not_called()

    def test_invalid_plan_rejected_before_any_worker_or_record(self):
        cases = [ {'agent': []}, {'agent': 'verify', 'id': []},
                  {'agent': 'verify', 'depends': [[]]},
                  {'agent': 'verify', 'depends': ['a', 'a']},
                  {'agent': 'writer', 'input': {'instruction': 7}},
                  {'agent': 'browser', 'input': {'url': 'https://u:p@example.com'}} ]
        with patch.object(agents, 'worker') as work:
            for extra in cases:
                tasks = [{'id': 'a', 'agent': 'verify'}, {'id': 'b', 'agent': 'verify', **extra}]
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    agents.execute('alice', tasks)
            work.assert_not_called()
        self.assertFalse(list(agents.STORE.glob('**/*.json')))

    def test_contract_saved_before_effect_and_cannot_be_spoofed(self):
        task = {'id': 'a', 'agent': 'browser',
                'execution': {'owner': 'bob', 'risk': 'read', 'replay_safe': True}}
        def effect(owner, step, deps):
            record = agents.recent(owner)['tasks'][0]['execution']
            self.assertEqual(record['owner'], 'alice')
            self.assertEqual(record['risk'], 'external_effect_possible')
            self.assertFalse(record['replay_safe'])
            self.assertEqual(record['attempt'], 1)
            self.assertEqual(record['outcome'], 'pending')
            raise RuntimeError('Timeout after external effect')
        with patch.object(agents, 'worker', side_effect=effect):
            job = agents.execute('alice', [task])
        self.assertEqual(job['tasks'][0]['execution']['outcome'], 'effect_unknown')
        with patch.object(agents, 'worker') as work:
            with self.assertRaises(ValueError): agents.continue_job('alice', job['id'])
            work.assert_not_called()
        self.assertEqual(task['execution']['owner'], 'bob')

    def test_read_failure_remains_recoverable(self):
        with patch.object(agents, 'worker', side_effect=RuntimeError('offline')):
            job = agents.execute('alice', [{'id': 'a', 'agent': 'research'}])
        self.assertEqual(job['tasks'][0]['execution']['outcome'], 'failed')
        with patch.object(agents, 'worker', return_value={'state': 'done'}):
            done = agents.continue_job('alice', job['id'])
        self.assertEqual(done['tasks'][0]['execution']['attempt'], 2)
        self.assertEqual(done['tasks'][0]['execution']['outcome'], 'verified')

    def test_contract_does_not_grant_approval(self):
        with patch.object(agents, 'worker', return_value={'state': 'approval', 'id': 'exact'}):
            job = agents.execute('alice', [{'id': 'a', 'agent': 'browser'}])
        self.assertEqual(job['state'], 'approval')
        self.assertEqual(job['tasks'][0]['execution']['outcome'], 'approval_required')
        with patch.object(browser_agent, 'run') as run:
            with self.assertRaises(ValueError): agents.resume('alice', 'wrong')
            run.assert_not_called()

    def test_bounds_and_returned_data_are_independent(self):
        for data in ({'request': ' '}, {'request': 'x' * 20001}, {'request': 'a\x00b'}):
            with self.assertRaises(ValueError): tools.validate_input('coder', data)
        data = {'request': 'fix'}
        result = tools.validate_input('coder', data)
        result['request'] = 'changed'
        self.assertEqual(data['request'], 'fix')


if __name__ == '__main__': unittest.main()
