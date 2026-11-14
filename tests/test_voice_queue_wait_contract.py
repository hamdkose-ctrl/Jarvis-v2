"""Voice-first queued turn lifecycle: bounded wait is not execution time.

These tests exercise real request journal state and the phone's queued HTTP
timeout; no provider, second Scheduler, runtime profile switch or network.
"""
from __future__ import annotations

import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import brain_entry, engine_queue, requests_state


class QueuedTurnLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(
            requests_state, '_journal', Path(self.temp.name) / 'requests.json'))
        self.enterContext(patch.object(requests_state, '_records', {}))
        self.pc = SimpleNamespace(name='Alice', slug='alice')
        self.runtime = SimpleNamespace(
            _tr_lower=str.casefold, slugify=str.casefold,
            pc_profile=lambda: self.pc,
            _get_profile=lambda name:self.pc,
            _emit_for=Mock(), _record_failure=Mock(),
            requests_state=requests_state, events=queue.Queue(),
        )

    def submit(self, rid='a'):
        with patch.object(brain_entry, 'fast_lane', return_value=None):
            return engine_queue.submit(
                self.runtime, 'Bir de bu belgeyi araştır.',
                user='Alice', rid=rid,
            )

    def test_new_natural_language_turn_survives_long_foreground_queue(self):
        self.assertTrue(self.submit('waiting'))
        rec = requests_state._records[('alice', 'waiting')]
        self.assertEqual(rec['state'], 'queued')
        self.assertEqual(rec['execution_seconds'], 90)
        self.assertGreater(rec['deadline'], time.monotonic() + 295)
        self.assertEqual(self.runtime.events.get_nowait(),
                         ('command', 'Bir de bu belgeyi araştır.', 'yazı',
                          'Alice', 'waiting'))
        # Simulate most of the bounded queue allowance passing. Activation
        # gets a fresh execution clock instead of inheriting a nearly
        # exhausted one, without any model/provider execution.
        rec['deadline'] = time.monotonic() + .2
        with requests_state.activate('alice', 'waiting'):
            self.assertEqual(rec['state'], 'running')
            self.assertGreater(rec['deadline'], time.monotonic() + 85)
            self.assertNotIn('execution_seconds', rec)
        self.assertEqual(rec['state'], 'done')
        self.assertFalse(self.submit('waiting'))  # durable RID tombstone

    def test_expired_queue_turn_is_never_revived_or_dispatched(self):
        self.assertTrue(self.submit('expired'))
        rec = requests_state._records[('alice', 'expired')]
        rec['deadline'] = time.monotonic() - 1
        self.assertEqual(requests_state.request_state('alice','expired'),
                         'cancelled')
        with self.assertRaises(requests_state.Cancelled):
            with requests_state.activate('alice', 'expired'):
                self.fail('expired work executed')
        self.assertEqual(rec['state'], 'cancelled')
        self.assertFalse(self.submit('expired'))

    def test_cancelled_waiting_turn_never_restarts(self):
        self.assertTrue(self.submit('cancel-1'))
        requests_state.cancel('alice', 'cancel-1')
        with self.assertRaises(requests_state.Cancelled):
            with requests_state.activate('alice', 'cancel-1'):
                self.fail('cancelled work executed')
        self.assertEqual(requests_state.request_state('alice','cancel-1'),
                         'cancelled')

    def test_unrelated_owner_and_background_deadline_unchanged(self):
        self.assertTrue(requests_state.register('alice', 'plain', seconds=120))
        self.assertTrue(requests_state.register_background(
            'bob', 'background', seconds=1800))
        plain = requests_state._records[('alice','plain')]
        old = plain['deadline']
        with requests_state.activate('alice','plain'):
            self.assertEqual(plain['deadline'], old)
        self.assertEqual(requests_state.request_state('bob','background'),
                         'queued')
        self.assertIsNone(requests_state.request_state('alice','background'))

    def test_phone_http_wait_timeout_does_not_cancel_queued_turn(self):
        from modules.phone import PhoneServer
        engine = SimpleNamespace(
            _log_id=0, pc_profile=lambda: self.pc,
            requests_state=requests_state,
            stop_event=threading.Event(), response_waiters=None,
            submit=lambda text, source, user, rid=None:
                requests_state.register('alice', rid, seconds=300,
                                        execution_seconds=90),
        )
        with patch('modules.phone.get_token', return_value='not-real-token'), \
             patch('modules.android_setup.SetupGrants', return_value=Mock()):
            phone = PhoneServer(engine)
        with patch.object(phone, 'user_of', return_value='Alice'), \
             patch.object(phone, 'user_filter',
                          return_value=lambda name:True):
            answer = phone.ask('Yeni bir araştırma yap.',user='Alice',
                               timeout=0)
        self.assertIn('hâlâ sırada',answer)
        self.assertEqual(len(requests_state._records),1)
        rid=next(iter(requests_state._records))[1]
        self.assertEqual(requests_state.request_state('alice',rid),'queued')

    def test_phone_timeout_still_cancels_running_request(self):
        from modules.phone import PhoneServer
        engine = SimpleNamespace(
            _log_id=0, pc_profile=lambda:self.pc,
            requests_state=requests_state, stop_event=threading.Event(),
            response_waiters=None,
        )
        def active_submit(text, source, user, rid=None):
            requests_state.register('alice', rid)
            requests_state._records[('alice',rid)]['state']='running'
            return True
        engine.submit = active_submit
        with patch('modules.phone.get_token', return_value='not-real-token'), \
             patch('modules.android_setup.SetupGrants', return_value=Mock()):
            phone = PhoneServer(engine)
        with patch.object(phone, 'user_of', return_value='Alice'), \
             patch.object(phone, 'user_filter',
                          return_value=lambda name:True):
            answer = phone.ask('İşlem',user='Alice',timeout=0)
        rid = next(iter(requests_state._records))[1]
        self.assertEqual(requests_state.request_state('alice',rid),'cancelled')
        self.assertIn('yanıt veremedi',answer)


if __name__ == '__main__':
    unittest.main()
