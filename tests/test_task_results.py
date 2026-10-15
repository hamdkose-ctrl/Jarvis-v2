import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import task_results as results, task_agents as agents, developer


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'evidence.png'
        self.path.write_bytes(b'screenshot bytes')

    def browser(self):
        return {'state': 'done', 'steps': [{'op': 'read', 'verified': True}],
                'page': {'url': 'https://example.com'}, 'image': str(self.path)}

    def test_browser_evidence_changes_are_rejected(self):
        sealed = results.seal('browser', self.browser())
        self.assertTrue(results.verify(sealed))
        self.path.write_bytes(b'changed')
        with self.assertRaises(ValueError): results.verify(sealed)

    def test_browser_requires_all_steps_and_real_screenshot(self):
        for update in ({'steps': []}, {'steps': [{'verified': False}]},
                       {'image': str(self.path.parent / 'missing')}, {'page': {}}):
            with self.assertRaises(ValueError): results.seal('browser', {**self.browser(), **update})

    def test_writer_requires_digest_and_unchanged_file(self):
        output = {'state': 'done', 'text': 'report', 'file': str(self.path)}
        with self.assertRaises(ValueError): results.seal('writer', output)
        output['sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        sealed = results.seal('writer', output)
        self.path.unlink()
        with self.assertRaises(ValueError): results.verify(sealed)

    def test_research_requires_source_read_and_nonempty_answer(self):
        output = {'state': 'done', 'text': 'answer', 'source': 'https://example.com', 'source_chars': 80}
        self.assertTrue(results.verify(results.seal('research', output)))
        for update in ({'source_chars': 0}, {'source_chars': True}, {'source': 'file:///etc/passwd'}, {'text': ' '}):
            with self.assertRaises(ValueError): results.seal('research', {**output, **update})

    def test_code_missing_stale_failed_tests_or_no_draft_cannot_complete(self):
        for files, ok in ((['a.py'], None), (['a.py'], False), ([], True)):
            state = {'enabled': True, 'unlocked': True, 'draft_files': files, 'draft_test_ok': ok}
            with patch.object(developer, 'status', return_value=state), patch.object(developer, 'handle', return_value='done'):
                with self.assertRaises(ValueError): agents.worker('alice', {'agent': 'coder', 'input': {'request': 'fix'}}, {})

    def test_successful_code_reports_tested_draft(self):
        state = {'enabled': True, 'unlocked': True, 'draft_files': ['a.py'], 'draft_test_ok': True}
        delivery={'owner':'alice','files':[{'file':str(self.path),'sha256':results.file_digest(self.path)}],
                  'file':str(self.path),'test_log':str(self.path),'test_log_sha256':results.file_digest(self.path)}
        with patch.object(developer, 'status', return_value=state), patch.object(developer, 'handle', return_value='tested'), \
             patch.object(developer,'deliver_code',return_value=delivery):
            output = agents.worker('alice', {'agent': 'coder', 'input': {'request': 'fix'}}, {})
        self.assertTrue(results.verify(output))

    def test_approval_and_unavailable_are_never_sealed_as_success(self):
        for state in ('approval', 'unavailable', 'failed', 'blocked'):
            output = results.seal('browser', {'state': state})
            self.assertNotIn('verification', output)
            with self.assertRaises(ValueError): results.verify(output)

    def test_legacy_and_unknown_results_cannot_verify(self):
        for output in ({'state': 'done', 'text': 'model claims done'},
                       {'state': 'done', 'verification': {'version': 1, 'agent': 'unknown'}}):
            with self.assertRaises(ValueError): results.verify(output)

    def test_verifier_rechecks_dependency_file(self):
        output = results.seal('browser', self.browser())
        task = {'agent': 'verify'}
        self.assertTrue(results.verify(agents.worker('alice', task, {'browser': output})))
        self.path.unlink()
        with self.assertRaises(ValueError): agents.worker('alice', task, {'browser': output})

    def test_empty_and_symlink_files_cannot_prove_success(self):
        self.path.write_bytes(b'')
        with self.assertRaises(ValueError): results.seal('browser', self.browser())
        self.path.write_bytes(b'screenshot bytes')
        original=Path.is_symlink
        with patch.object(Path,'is_symlink',autospec=True,side_effect=lambda p:p==self.path or original(p)):
            with self.assertRaises(ValueError): results.seal('browser', self.browser())

    def test_real_symlink_cannot_prove_success_when_os_permits_creation(self):
        self.path.unlink()
        try:self.path.symlink_to(Path(__file__).resolve())
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:self.skipTest('Windows kullanıcı hesabında symlink oluşturma izni yok.')
            raise
        with self.assertRaises(ValueError):results.seal('browser',self.browser())

    def test_resume_rechecks_completed_browser_without_replaying(self):
        from modules import browser_agent
        with patch.object(agents, 'STORE', self.path.parent / 'tasks'), patch.object(browser_agent, 'STORE', self.path.parent / 'browser'):
            with patch.object(agents, 'browser_task', return_value=self.browser()):
                job = agents.execute('alice', [{'id': 'a', 'agent': 'browser'}])
            self.path.unlink()
            with patch.object(agents, 'worker') as work:
                with self.assertRaises(ValueError): agents.continue_job('alice', job['id'])
                work.assert_not_called()


if __name__ == '__main__': unittest.main()
