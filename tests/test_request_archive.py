"""Bounded hot request journal without losing durable duplicate rejection."""
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from modules import requests_state as state

class RequestArchiveTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for name,value in [('_journal',Path(folder.name)/'requests.json'),('_records',{}),
                           ('_TERMINAL_LIMIT',3),('_current',ContextVar('archive_request',default=None))]:
            p=patch.object(state,name,value);p.start();self.addCleanup(p.stop)

    def completed(self,rid):
        self.assertTrue(state.register('alice',rid))
        with state.activate('alice',rid):state.check()

    def test_old_ids_rejected_after_compaction_and_reload(self):
        for n in range(10):self.completed(str(n))
        self.assertEqual(len(state._records),3)
        rows=json.loads(state._journal.read_text());self.assertEqual(len(rows),3)
        for n in range(10):self.assertFalse(state.register('alice',str(n)))
        state._records.clear()
        state._records.update({(r['user'],r['rid']):{'state':r['state'],'deadline':0} for r in rows})
        self.assertFalse(state.register('alice','0'))
        self.assertTrue(state.register('bob','0'))
        self.assertTrue(state.is_cancelled('alice','0'))

    def test_bare_stop_never_selects_queued_or_background_work(self):
        state.register('alice', 'planner')
        state.register('alice', 'queued-voice')
        state.register('bob', 'other')
        self.assertEqual(state.cancel_foreground('alice'), ('none', None))
        self.assertEqual(state.request_state('alice', 'planner'), 'queued')
        self.assertEqual(state.request_state('alice', 'queued-voice'), 'queued')
        self.assertEqual(state.request_state('bob', 'other'), 'queued')
        with self.assertRaises(ValueError):
            state.cancel('alice', None)
        self.assertEqual(state.request_state('alice', 'planner'), 'queued')
        with state.activate('alice', 'planner'):
            self.assertEqual(state.cancel_foreground('alice'), ('none', None))
            state.check()

    def test_bare_stop_cancels_only_running_foreground(self):
        state.register('alice', 'voice')
        state.register('alice', 'planner')
        state.register('bob', 'other')
        with state.activate('alice', 'voice', foreground=True):
            self.assertEqual(state.cancel_foreground('alice'), ('cancelled', 'voice'))
            with self.assertRaises(state.Cancelled):
                state.check()
        self.assertTrue(state.is_cancelled('alice', 'voice'))
        self.assertTrue(state.speech_muted('alice', 'voice'))
        self.assertFalse(state.speech_muted('alice', 'planner'))
        self.assertFalse(state.is_cancelled('alice', 'planner'))
        self.assertFalse(state.is_cancelled('bob', 'other'))
        self.assertEqual(state.cancel_foreground('alice'), ('none', None))

    def test_bare_stop_rejects_ambiguous_foreground(self):
        state.register('alice', 'voice-1')
        state.register('alice', 'voice-2')
        with state.activate('alice', 'voice-1', foreground=True):
            with state.activate('alice', 'voice-2', foreground=True):
                self.assertEqual(state.cancel_foreground('alice'), ('ambiguous', None))
                self.assertFalse(state.is_cancelled('alice', 'voice-1'))
                self.assertFalse(state.is_cancelled('alice', 'voice-2'))

    def test_targeted_cancel_does_not_touch_sibling_or_other_owner(self):
        for owner, rid in [('alice', 'a'), ('alice', 'b'), ('bob', 'a')]:
            self.assertTrue(state.register(owner, rid))
        state.cancel('alice', 'a')
        self.assertTrue(state.is_cancelled('alice', 'a'))
        self.assertFalse(state.is_cancelled('alice', 'b'))
        self.assertFalse(state.is_cancelled('bob', 'a'))

    def test_bare_stop_never_revives_an_expired_request(self):
        state.register('alice', 'expired', seconds=-1)
        self.assertEqual(state.cancel_foreground('alice'), ('none', None))
        self.assertTrue(state.is_cancelled('alice', 'expired'))

    def test_active_and_transcription_handoff_not_pruned(self):
        state.register('alice','live')
        with state.activate('alice','live',complete=False):
            for n in range(10):self.completed(str(n))
            state.check()
        self.assertEqual(state._records[('alice','live')]['state'],'queued')
        state.cancel('alice','live');self.assertTrue(state.is_cancelled('alice','live'))

    def test_failed_journal_replace_keeps_ram_and_duplicate_barrier(self):
        for n in range(3):self.completed(str(n))
        state.register('alice','new')
        with patch.object(state.os,'replace',side_effect=OSError('disk failure')):
            with state.activate('alice','new'):pass
        self.assertIn(('alice','0'),state._records)
        self.assertFalse(state.register('alice','0'))
        state._save()
        self.assertEqual(len(state._records),3)

    def test_archive_failure_keeps_new_request_retryable(self):
        for n in range(4):self.completed(str(n))
        state._records[('alice','pending-terminal')]={'state':'done','deadline':0}
        with patch.object(state.sqlite3,'connect',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(OSError):state.register('alice','new')
        self.assertNotIn(('alice','new'),state._records)
        self.assertTrue(state.register('alice','new'))

    def test_corrupt_archive_fails_closed(self):
        state._archive_path().write_bytes(b'not a database')
        with self.assertRaises(OSError):state.register('alice','new')
        self.assertFalse(state._records)

    def test_cancelled_waiting_command_remains_blocked_after_archiving(self):
        state.register('alice','waiting');state.cancel('alice','waiting')
        for n in range(5):self.completed(str(n))
        self.assertNotIn(('alice','waiting'),state._records)
        with self.assertRaises(state.Cancelled):
            with state.activate('alice','waiting'):self.fail('cancelled command ran')
        self.assertIsNone(state._current.get())

    def test_expired_unconsumed_queue_does_not_accumulate_forever(self):
        for n in range(10):
            state.register('alice',str(n),seconds=-1)
        self.assertLessEqual(len(state._records),3)
        self.assertTrue(state.is_cancelled('alice','0'))
        with self.assertRaises(state.Cancelled):
            with state.activate('alice','0'):self.fail('expired command ran')
