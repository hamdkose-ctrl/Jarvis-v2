"""Yürütücü birleştirme (Aşama 2 adım 4) öncesi sabitleme: task_agents'ın başka modüllerin kullandığı yüzeyi
ve sabit komutlarının bugünkü davranışı. Taşıma/silme bu testleri bozmamalı ya da bilinçli güncellemeli."""
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import task_agents as agents

ROOT = Path(__file__).resolve().parents[1]


def _used_attributes():
    """modules/, web*.py ve main.py içinde `task_agents.<ad>` olarak başvurulan her ad (testler hariç)."""
    used = {}
    files = list((ROOT / 'modules').glob('*.py')) + list(ROOT.glob('web*.py')) + [ROOT / 'main.py']
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in ('task_agents', 'agents') and path.name != 'task_agents.py'):
                if node.value.id == 'agents' and 'task_agents' not in path.read_text(encoding='utf-8'):
                    continue
                used.setdefault(node.attr, set()).add(path.name)
    return used


class SurfaceTests(unittest.TestCase):
    def test_every_name_other_modules_use_still_exists(self):
        used = _used_attributes()
        self.assertTrue(used, 'başvuru bulunamadı: tarama bozuk')
        missing = {name: sorted(files) for name, files in used.items() if not hasattr(agents, name)}
        self.assertEqual(missing, {})

    def test_known_entry_points_are_present(self):
        for name in ('worker', 'execute', 'continue_job', 'cancel_job', 'resume', 'handle', 'render', 'render_summary',
                     'recent', 'history', 'validate', 'Busy', '_root', '_job_path', '_active', 'memory_context'):
            with self.subTest(name):
                self.assertTrue(hasattr(agents, name))

    def test_worker_catalog_lists_every_executable_worker(self):
        from modules import task_tools
        self.assertEqual(set(agents.WORKER_CATALOG), {'media', 'publish', 'account', 'research', 'finance', 'computer', 'writer', 'browser', 'coder', 'verify'})
        self.assertTrue(set(task_tools.CATALOG) >= {'media', 'publish', 'account', 'research', 'writer', 'verify'})


class WorkerMoveTests(unittest.TestCase):
    def test_workers_live_in_task_workers_and_task_agents_delegates(self):
        from modules import task_workers
        self.assertTrue(callable(task_workers.run) and callable(task_workers.browser_task))
        self.assertIs(agents.browser_task, task_workers.browser_task)
        with patch.object(task_workers, 'run', return_value={'state': 'done'}) as run:
            self.assertEqual(agents._worker('alice', {'agent': 'verify'}, {}), {'state': 'done'})
        run.assert_called_once()

    def test_unknown_agent_is_still_rejected_by_the_worker(self):
        from modules import task_workers
        with self.assertRaises(ValueError):
            task_workers.run('alice', {'agent': 'nope', 'input': {}}, {})


class FixedCommandTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        patcher = patch.object(agents, 'STORE', Path(tmp.name) / 'tasks'); patcher.start(); self.addCleanup(patcher.stop)

    def test_flow_catalog_command_lists_flows(self):
        from modules.task_workflows import CATALOG
        text = agents.handle('alice', 'Görev Akışları')
        for key in CATALOG:
            self.assertIn(key + ':', text)

    def test_flow_command_builds_the_catalog_plan_and_runs_it(self):
        seen = {}
        def fake_execute(owner, tasks, instruction='', emit=None, **kw):
            seen.update(owner=owner, tasks=tasks, instruction=instruction)
            return {'id': 'j1', 'state': 'done', 'tasks': [], 'outputs': {}}
        with patch.object(agents, 'execute', side_effect=fake_execute), patch.object(agents, 'render', return_value='ÖZET'):
            self.assertEqual(agents.handle('alice', 'görev akışı rapor: https://example.com | kısa rapor'), 'ÖZET')
        self.assertEqual(seen['owner'], 'alice')
        self.assertEqual([t['agent'] for t in seen['tasks']], ['research', 'writer', 'verify'])
        self.assertEqual(seen['tasks'][1]['depends'], ['source'])

    def test_flow_command_with_bad_syntax_raises_instead_of_running(self):
        with patch.object(agents, 'execute') as run:
            with self.assertRaises(ValueError):
                agents.handle('alice', 'görev akışı rapor: yalnız metin')
        run.assert_not_called()

    def test_first_mail_attachments_without_history_plans_list_then_attachment(self):
        seen = {}
        def fake_execute(owner, tasks, instruction='', emit=None, **kw):
            seen['tasks'] = tasks
            return {'id': 'j1', 'state': 'done', 'tasks': [], 'outputs': {}}
        with patch.object(agents, 'recent', return_value=None), patch.object(agents, 'execute', side_effect=fake_execute), \
             patch.object(agents, 'render_summary', return_value='X'):
            agents.handle('alice', 'ilk mailin eklerini göster', summary=True)
        ops = [(t['id'], t['input'].get('operation')) for t in seen['tasks']]
        self.assertEqual(ops, [('list', 'list_unread'), ('attachment', 'list_attachments')])
        self.assertEqual(seen['tasks'][1]['depends'], ['list'])

    def test_mail_attachment_command_with_angle_brackets_is_explained_not_run(self):
        with patch.object(agents, 'execute') as run:
            text = agents.handle('alice', 'görev mail ek <abc>')
        run.assert_not_called()
        self.assertIn('Mail kimliği', text)

    def test_attachment_read_command_needs_index_exactly_when_reading(self):
        with patch.object(agents, 'execute') as run:
            with self.assertRaises(ValueError):
                agents.handle('alice', 'görev mail ek oku abc123')       # okuma: sıra şart
            with self.assertRaises(ValueError):
                agents.handle('alice', 'görev mail ekleri abc123 2')     # liste: sıra olmaz
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
