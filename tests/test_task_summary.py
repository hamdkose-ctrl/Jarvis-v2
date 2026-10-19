"""Result summaries use real privacy.redact and no live device/model."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class TaskSummaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(patch.dict(os.environ, {'JARVIS_DATA_DIR': temporary.name}))
        from modules import task_summary, privacy
        self.summary, self.privacy = task_summary, privacy

    def job(self, **changes):
        return {'request': 'Rapor hazırla', 'state': 'done', 'steps': [
            {'text': 'Kaynakları oku', 'state': 'done'},
            {'text': 'Rapor yaz', 'state': 'pending'}], **changes}

    def test_done_left_and_stopped_are_separate(self):
        result = self.summary.summarize(self.job(state='cancelled'))
        self.assertEqual(result, {'title': 'Rapor hazırla', 'done': ['Kaynakları oku'],
                                 'left': ['Rapor yaz'], 'stopped': True, 'verified': False})

    def test_done_is_not_automatically_verified(self):
        steps = [{'text': 'Dosya yaz', 'state': 'done'}]
        self.assertFalse(self.summary.summarize(self.job(steps=steps))['verified'])
        self.assertTrue(self.summary.summarize(self.job(steps=steps, verified=True))['verified'])
        steps[0]['verified'] = True
        self.assertTrue(self.summary.summarize(self.job(steps=steps))['verified'])

    def test_partial_failed_or_stopped_cannot_claim_full_verification(self):
        for state in ('cancelled', 'stopped', 'failed', 'incomplete', 'running'):
            with self.subTest(state=state):
                self.assertFalse(self.summary.summarize(self.job(state=state, verified=True))['verified'])
        self.assertFalse(self.summary.summarize(self.job(verified=True))['verified'])
        steps = [{'text': 'Kontrol', 'state': 'failed', 'verified': True}]
        self.assertEqual(self.summary.summarize(self.job(steps=steps, verified=True))['left'], ['Kontrol'])

    def test_empty_missing_malformed_jobs_return_empty_summary(self):
        empty = {'title': '', 'done': [], 'left': [], 'stopped': False, 'verified': False}
        for job in (None, False, 0, [], '', {}, {'request': 'x'}, self.job(steps=None),
                    self.job(steps=[None]), self.job(steps=[{'text': [], 'state': 'done'}]),
                    self.job(state=[]), self.job(request=12)):
            with self.subTest(job=job):
                self.assertEqual(self.summary.summarize(job), empty)

    def test_all_user_text_is_masked_even_when_redaction_setting_is_off(self):
        secret = 'token=PRIVATE_SECRET_VALUE alice@example.org 0532 123 45 67'
        job = self.job(request=secret, steps=[{'text': secret, 'state': 'done'}])
        with patch.object(self.privacy, 'redact_enabled', return_value=False), \
                patch.object(self.privacy, 'mode', return_value='normal'):
            result = self.summary.summarize(job)
        output = str(result)
        for value in ('PRIVATE_SECRET_VALUE', 'alice@example.org', '0532 123 45 67'):
            self.assertNotIn(value, output)
        self.assertIn('gizlendi', output)

    def test_redact_before_limiting_does_not_leak_a_partial_secret(self):
        job = self.job(request='x' * 190 + ' token=' + 'PRIVATE' * 30,
                       steps=[{'text': 'x' * 190 + ' token=' + 'PRIVATE' * 30, 'state': 'pending'}])
        result = self.summary.summarize(job)
        self.assertNotIn('PRIVATE', str(result))
        self.assertLessEqual(len(result['title']), 200)
        self.assertLessEqual(len(result['left'][0]), 200)

    def test_unicode_limit_whitespace_and_step_title_alias(self):
        result = self.summary.summarize(self.job(title='ş' * 201,
            steps=[{'title': '  Çıktı\n kontrolü  ', 'state': 'completed'}]))
        self.assertEqual(len(result['title']), 200)
        self.assertEqual(result['done'], ['Çıktı kontrolü'])

    def test_verification_requires_actual_boolean_and_nonempty_done_steps(self):
        steps = [{'text': 'Kontrol', 'state': 'done', 'verified': True}]
        for value in ('true', 1, None):
            with self.subTest(value=value):
                bad = [{'text': 'Kontrol', 'state': 'done', 'verified': value}]
                self.assertFalse(self.summary.summarize(self.job(steps=bad, verified=value))['verified'])
        self.assertTrue(self.summary.summarize(self.job(steps=steps))['verified'])
        self.assertFalse(self.summary.summarize(self.job(steps=[], verified=True))['verified'])

    def test_every_non_done_step_remains_visible_as_left(self):
        states = ['pending', 'working', 'failed', 'blocked', 'approval', 'cancelled', 'unknown']
        steps = [{'text': state, 'state': state} for state in states]
        self.assertEqual(self.summary.summarize(self.job(steps=steps))['left'], states)

    def test_inputs_and_returned_lists_do_not_share_mutable_state(self):
        job = self.job()
        before = copy.deepcopy(job)
        result = self.summary.summarize(job)
        result['done'].clear()
        result['left'].append('changed')
        self.assertEqual(job, before)
        self.assertEqual(self.summary.summarize(job)['done'], ['Kaynakları oku'])


if __name__ == '__main__':
    unittest.main()
