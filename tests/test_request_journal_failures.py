"""Real queue/journal regressions with injected filesystem write/replace failures."""
from contextvars import ContextVar
import json
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules import engine_queue, requests_state as state


class RequestJournalFailureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for attribute, value in [('_journal', Path(folder.name)/'requests.json'), ('_records', {}), ('_current', ContextVar('test_request', default=None))]:
            patched = patch.object(state, attribute, value);patched.start();self.addCleanup(patched.stop)
        self.runtime = SimpleNamespace(_tr_lower=str.lower, slugify=str.lower,
            pc_profile=lambda: SimpleNamespace(name='Alice'), requests_state=state, events=queue.Queue())

    def test_write_and_replace_failure_leave_no_phantom_request_and_retry_queues_once(self):
        state.register('alice', 'existing')
        for target in ('write', 'replace'):
            with self.subTest(target=target):
                rid = 'failed-' + target
                before = state._journal.read_bytes()
                broken = patch.object(Path, 'write_text', side_effect=OSError('disk full')) if target == 'write' else patch.object(state.os, 'replace', side_effect=OSError('disk full'))
                with broken, self.assertRaises(OSError):
                    engine_queue.submit(self.runtime, 'merhaba', rid=rid)
                self.assertTrue(self.runtime.events.empty())
                self.assertNotIn(('alice', rid), state._records)
                self.assertEqual(state._journal.read_bytes(), before)
                self.assertIn(('alice', 'existing'), state._records)
                self.assertTrue(engine_queue.submit(self.runtime, 'merhaba', rid=rid))
                self.assertFalse(engine_queue.submit(self.runtime, 'merhaba', rid=rid))
                self.assertEqual(self.runtime.events.get_nowait(), ('command', 'merhaba', 'yazı', 'Alice', rid))
                self.assertTrue(self.runtime.events.empty())

    def test_failed_completion_keeps_duplicate_guard_and_allows_next_queued_command(self):
        for rid in ('first', 'second'):
            engine_queue.submit(self.runtime, 'merhaba', rid=rid)
        completed = []
        with patch.object(state.os, 'replace', side_effect=OSError('disk full')), self.assertLogs('modules.requests_state', level='ERROR'):
            while not self.runtime.events.empty():
                _, _, _, user, rid = self.runtime.events.get_nowait()
                with state.activate(user.lower(), rid):
                    state.check();completed.append(rid)
                self.assertIsNone(state._current.get())
        self.assertEqual(completed, ['first', 'second'])
        for rid in completed:
            self.assertEqual(state._records[('alice', rid)]['state'], 'done')
            self.assertFalse(state.register('alice', rid))
        # A subsequent successful save retains the failed completion tombstones.
        state.register('alice', 'third')
        saved = {row['rid']: row['state'] for row in json.loads(state._journal.read_text())}
        self.assertEqual(saved['first'], 'done');self.assertEqual(saved['second'], 'done')

    def test_nested_completion_failure_restores_parent_context(self):
        state.register('alice', 'parent');state.register('alice', 'child')
        with state.activate('alice', 'parent'):
            with patch.object(state.os, 'replace', side_effect=OSError('disk full')), self.assertLogs('modules.requests_state', level='ERROR'):
                with state.activate('alice', 'child'):
                    self.assertEqual(state._current.get(), ('alice', 'child'))
            self.assertEqual(state._current.get(), ('alice', 'parent'))
        self.assertIsNone(state._current.get())

    def test_completion_write_failure_does_not_replace_body_exception(self):
        state.register('alice', 'request')
        with patch.object(state.os, 'replace', side_effect=OSError('disk full')), self.assertLogs('modules.requests_state', level='ERROR'):
            with self.assertRaisesRegex(ValueError, 'work failed'):
                with state.activate('alice', 'request'):
                    raise ValueError('work failed')
        self.assertIsNone(state._current.get())

    def test_expired_request_still_cancels_when_journal_cannot_be_written(self):
        state.register('alice', 'expired', seconds=-1)
        with patch.object(state.os, 'replace', side_effect=OSError('disk full')), self.assertLogs('modules.requests_state', level='ERROR'):
            with self.assertRaises(state.Cancelled):
                with state.activate('alice', 'expired'):
                    self.fail('Expired work was executed')
        self.assertIsNone(state._current.get())
        self.assertFalse(state.register('alice', 'expired'))

    def test_cancellation_does_not_revert_when_journal_save_fails(self):
        state.register('alice', 'request')
        with patch.object(state.os, 'replace', side_effect=OSError('disk full')), self.assertLogs('modules.requests_state', level='ERROR'):
            state.cancel('alice', 'request')
        self.assertTrue(state.is_cancelled('alice', 'request'))
        self.assertFalse(state.register('alice', 'request'))

    def test_unexpected_save_error_is_not_swallowed_but_context_is_restored(self):
        state.register('alice', 'request')
        with patch.object(state, '_save', side_effect=ValueError('journal bug')):
            with self.assertRaisesRegex(ValueError, 'journal bug'):
                with state.activate('alice', 'request'):
                    pass
        self.assertIsNone(state._current.get())
