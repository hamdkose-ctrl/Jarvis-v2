import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import task_workers


class Phase4FileWorkerWiringTests(unittest.TestCase):
    def test_file_worker_extracts_obligations_with_file_evidence(self):
        observation = SimpleNamespace(
            path='C:/Users/alice/Documents/plan.txt',
            file_identity='C:/Users/alice/Documents/plan.txt',
            content_digest='a' * 64,
            reason_code='OK',
            warnings=[],
            truncated=False,
            continuation=None,
            locations=[SimpleNamespace(text='Rapor 2026-12-01 tarihine kadar hazırlanmalı.', page=None, line=1, sheet=None, cell_or_range=None)],
        )
        with patch('modules.file_worker.extract', return_value=observation), \
             patch('modules.file_worker_extensions.extract_obligations', return_value=[
                 {'kind': 'deadline', 'text': 'Rapor 2026-12-01 tarihine kadar hazırlanmalı.', 'due': '2026-12-01', 'source': observation.path},
             ]) as obligations:
            result = task_workers.run('alice', {
                'id': 'file-1', 'agent': 'file', 'input': {'path': observation.path, 'operation': 'extract_obligations'},
                'execution': {},
            }, {})

        obligations.assert_called_once()
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['file_evidence']['digest'], observation.content_digest)
        self.assertEqual(result['obligations'][0]['due'], '2026-12-01')


if __name__ == '__main__':
    unittest.main()
