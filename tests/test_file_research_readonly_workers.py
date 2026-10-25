import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ReadOnlyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _fence(self, request, capability_id):
        digest = hashlib.sha256(
            json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()
        return {
            'owner': 'alice',
            'job_id': 'job-1',
            'step_id': 'step-1',
            'command_id': 'cmd-1',
            'attempt': 0,
            'expected_job_version': 3,
            'capability_id': capability_id,
            'capability_version': '1',
            'input_digest': 'sha256:' + digest,
        }

    def test_file_worker_lists_deterministically_without_writing(self):
        from modules import file_worker, worker_result

        (self.root / 'b.txt').write_text('beta', encoding='utf-8')
        (self.root / 'a.txt').write_text('alpha', encoding='utf-8')
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        request = {'operation': 'list', 'path': '.'}
        result = file_worker.run(self._fence(request, file_worker.CAPABILITY_ID), request, root=self.root)

        worker_result.validate(result)
        self.assertEqual(result['status'], 'succeeded')
        evidence = result['evidence'][0]
        self.assertEqual(evidence['kind'], 'directory_listing')
        self.assertEqual([row['name'] for row in evidence['content']], ['a.txt', 'b.txt'])
        self.assertEqual(evidence['summary'], '2 girdi okundu.')
        after = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(after, before)

    def test_file_worker_reads_document_with_digest_and_bounded_content(self):
        from modules import file_worker, worker_result

        source = self.root / 'notlar.txt'
        source.write_text('Birinci satır\nİkinci satır\nÜçüncü satır', encoding='utf-8')
        request = {'operation': 'read', 'path': 'notlar.txt', 'max_chars': 24}
        result = file_worker.run(self._fence(request, file_worker.CAPABILITY_ID), request, root=self.root)

        worker_result.validate(result)
        evidence = result['evidence'][0]
        self.assertEqual(evidence['kind'], 'file_content')
        self.assertEqual(evidence['source']['path'], 'notlar.txt')
        self.assertEqual(evidence['source']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertLessEqual(len(evidence['content']), 24)
        self.assertTrue(evidence['summary'])
        self.assertEqual(evidence['extractor'], 'modules.docs.read_document')

    def test_file_worker_rejects_escape_and_effect_operations(self):
        from modules import file_worker

        outside = self.root.parent / 'outside-readonly-worker.txt'
        outside.write_text('secret', encoding='utf-8')
        self.addCleanup(lambda: outside.unlink(missing_ok=True))

        escape = {'operation': 'read', 'path': '../' + outside.name}
        with self.assertRaises(file_worker.ReadOnlyViolation):
            file_worker.run(self._fence(escape, file_worker.CAPABILITY_ID), escape, root=self.root)

        for operation in ('write', 'delete', 'move', 'rename', 'download', 'upload', 'send'):
            with self.subTest(operation=operation):
                request = {'operation': operation, 'path': 'x.txt'}
                with self.assertRaises(file_worker.ReadOnlyViolation):
                    file_worker.run(self._fence(request, file_worker.CAPABILITY_ID), request, root=self.root)

    def test_file_worker_rejects_wrong_input_digest(self):
        from modules import file_worker

        request = {'operation': 'list', 'path': '.'}
        fence = self._fence(request, file_worker.CAPABILITY_ID)
        fence['input_digest'] = 'sha256:' + ('0' * 64)
        with self.assertRaises(file_worker.ReadOnlyViolation):
            file_worker.run(fence, request, root=self.root)

    def test_research_worker_reads_public_text_with_source_bound_evidence(self):
        from modules import research_worker, worker_result

        body = b'<html><main><h1>Baslik</h1><p>Kaynak metni burada ve yeterince uzun bir aciklama iceriyor.</p></main></html>'
        calls = []

        def fetcher(url):
            calls.append(url)
            return {'url': url, 'body': body, 'content_type': 'text/html; charset=utf-8'}

        request = {
            'operation': 'read',
            'url': 'https://example.com/article',
            'allowed_origins': ['https://example.com'],
            'max_chars': 200,
        }
        result = research_worker.run(
            self._fence(request, research_worker.CAPABILITY_ID), request, fetcher=fetcher
        )

        worker_result.validate(result)
        self.assertEqual(calls, ['https://example.com/article'])
        evidence = result['evidence'][0]
        self.assertEqual(evidence['kind'], 'research_source')
        self.assertEqual(evidence['source']['url'], 'https://example.com/article')
        self.assertEqual(evidence['source']['publisher'], 'example.com')
        self.assertEqual(evidence['source']['sha256'], hashlib.sha256(body).hexdigest())
        self.assertIn('Kaynak metni', evidence['content'])
        self.assertTrue(evidence['summary'])

    def test_research_worker_rejects_unapproved_origin_binary_and_effect_operations(self):
        from modules import research_worker

        def should_not_fetch(_url):
            raise AssertionError('fetch should not run')

        wrong_origin = {
            'operation': 'read',
            'url': 'https://example.net/article',
            'allowed_origins': ['https://example.com'],
        }
        with self.assertRaises(research_worker.ReadOnlyViolation):
            research_worker.run(
                self._fence(wrong_origin, research_worker.CAPABILITY_ID), wrong_origin, fetcher=should_not_fetch
            )

        binary = {
            'operation': 'read',
            'url': 'https://example.com/file.pdf',
            'allowed_origins': ['https://example.com'],
        }
        with self.assertRaises(research_worker.ReadOnlyViolation):
            research_worker.run(
                self._fence(binary, research_worker.CAPABILITY_ID),
                binary,
                fetcher=lambda url: {'url': url, 'body': b'%PDF', 'content_type': 'application/pdf'},
            )

        for operation in ('download', 'login', 'post', 'upload', 'send', 'publish'):
            with self.subTest(operation=operation):
                request = {
                    'operation': operation,
                    'url': 'https://example.com/article',
                    'allowed_origins': ['https://example.com'],
                }
                with self.assertRaises(research_worker.ReadOnlyViolation):
                    research_worker.run(
                        self._fence(request, research_worker.CAPABILITY_ID), request, fetcher=should_not_fetch
                    )

    def test_research_worker_rejects_wrong_input_digest_without_fetching(self):
        from modules import research_worker

        request = {
            'operation': 'read',
            'url': 'https://example.com/article',
            'allowed_origins': ['https://example.com'],
        }
        fence = self._fence(request, research_worker.CAPABILITY_ID)
        fence['input_digest'] = 'sha256:' + ('f' * 64)
        with patch('modules.public_sources.fetch') as fetcher:
            with self.assertRaises(research_worker.ReadOnlyViolation):
                research_worker.run(fence, request)
        fetcher.assert_not_called()


if __name__ == '__main__':
    unittest.main()
