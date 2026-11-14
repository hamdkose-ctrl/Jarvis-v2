"""Status bypasses the blocked command queue without changing the active profile."""
import queue
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from modules import engine_queue,goal_executor,requests_state

class ResponsivenessTests(unittest.TestCase):
    def test_status_while_execution_lock_is_held_keeps_owner_and_request_id(self):
        owner=SimpleNamespace(name='Alice',slug='alice')
        runtime=SimpleNamespace(_tr_lower=str.lower,slugify=str.lower,pc_profile=lambda:owner,
            _get_profile=lambda name:owner,requests_state=requests_state,events=queue.Queue(),
            _emit_for=Mock(),_execution_lock=threading.RLock())
        held=threading.Event();release=threading.Event()
        def blocked():
            with runtime._execution_lock:held.set();release.wait(2)
        thread=threading.Thread(target=blocked);thread.start();self.assertTrue(held.wait(1))
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(requests_state,'_journal',Path(tmp)/'requests.json'),patch.object(requests_state,'_records',{}),patch.object(goal_executor,'fast_status',return_value='Kayıtlı hedef yok.') as view:
                self.assertTrue(engine_queue.submit(runtime,'hedef durumu',user='Alice',rid='status-1'))
                view.assert_called_once_with('alice', details=False)
                self.assertTrue(runtime.events.empty())
                self.assertEqual(runtime._emit_for.call_args.args,(owner,'assistant','Kayıtlı hedef yok.','yazı'))
                self.assertEqual(runtime._emit_for.call_args.kwargs['rid'],'status-1')
                self.assertFalse(engine_queue.submit(runtime,'hedef durumu',user='Alice',rid='status-1'))
        finally:release.set();thread.join(1)

    def test_exact_goal_result_during_blocked_foreground_is_read_only(self):
        from modules import canonical_goal_flow, brain_entry
        alice=SimpleNamespace(name='Alice',slug='alice')
        bob=SimpleNamespace(name='Bob',slug='bob')
        runtime=SimpleNamespace(
            _tr_lower=str.lower,slugify=str.lower,pc_profile=lambda:alice,
            _get_profile=lambda name: bob if name=='Bob' else alice,
            requests_state=requests_state,events=queue.Queue(),
            _emit_for=Mock(),_execution_lock=threading.RLock(),
            _record_failure=Mock(),
        )
        busy=threading.Event()
        free=threading.Event()
        def other_owner_long_task():
            with runtime._execution_lock:
                busy.set()
                free.wait(3)
        thread=threading.Thread(target=other_owner_long_task)
        thread.start()
        self.assertTrue(busy.wait(1))
        goal_id='1'*16
        try:
            with tempfile.TemporaryDirectory() as tmp, \
                 patch.object(requests_state,'_journal',Path(tmp)/'requests.json'), \
                 patch.object(requests_state,'_records',{}), \
                 patch.object(canonical_goal_flow,'read_result_command',
                              return_value='Kanıtlı hedef sonucu') as result, \
                 patch.object(goal_executor,'cancel_job') as cancel, \
                 patch.object(brain_entry,'fast_lane',
                              side_effect=AssertionError('Must not route through Brain')):
                self.assertTrue(engine_queue.submit(
                    runtime, f'hedef sonucu {goal_id}', source='telefon',
                    user='Bob', rid='read-1'))
                result.assert_called_once_with('bob',f'hedef sonucu {goal_id}')
                cancel.assert_not_called()
                self.assertFalse(free.is_set(), 'the command waited for foreground')
                self.assertTrue(runtime.events.empty())
                self.assertEqual(runtime._emit_for.call_args.args,
                                 (bob,'assistant','Kanıtlı hedef sonucu','telefon'))
                self.assertEqual(runtime._emit_for.call_args.kwargs['rid'],'read-1')
                self.assertFalse(engine_queue.submit(
                    runtime, f'hedef sonucu {goal_id}', source='telefon',
                    user='Bob',rid='read-1'))
                result.assert_called_once()
        finally:
            free.set()
            thread.join(1)

    def test_exact_goal_cancel_during_foreground_never_cancels_siblings(self):
        from modules import brain_entry
        alice=SimpleNamespace(name='Alice',slug='alice')
        runtime=SimpleNamespace(
            _tr_lower=str.lower,slugify=str.lower,pc_profile=lambda:alice,
            _get_profile=lambda name:alice,
            requests_state=requests_state,events=queue.Queue(),
            _emit_for=Mock(),_execution_lock=threading.RLock(),
            _record_failure=Mock(),
        )
        locked=threading.Event()
        free=threading.Event()
        def blocking_turn():
            with runtime._execution_lock:
                locked.set()
                free.wait(3)
        thread=threading.Thread(target=blocking_turn)
        thread.start()
        self.assertTrue(locked.wait(1))
        goal_id='a'*16
        try:
            with tempfile.TemporaryDirectory() as tmp, \
                 patch.object(requests_state,'_journal',Path(tmp)/'requests.json'), \
                 patch.object(requests_state,'_records',{}), \
                 patch.object(goal_executor,'cancel_job',return_value='İptal kaydedildi') as cancel, \
                 patch.object(requests_state,'cancel',
                              side_effect=AssertionError('Global cancel forbidden')), \
                 patch.object(brain_entry,'fast_lane',
                              side_effect=AssertionError('No semantic guess needed')):
                self.assertTrue(engine_queue.submit(
                    runtime,f'hedef iptal {goal_id}',user='Alice',rid='cancel-id'))
                cancel.assert_called_once_with('alice',goal_id)
                self.assertFalse(free.is_set())
                self.assertTrue(runtime.events.empty())
                self.assertEqual(runtime._emit_for.call_args.args[2],
                                 'İptal kaydedildi')
                self.assertFalse(engine_queue.submit(
                    runtime,f'hedef iptal {goal_id}',user='Alice',rid='cancel-id'))
                cancel.assert_called_once()
        finally:
            free.set()
            thread.join(1)

    def test_uncertain_scoped_cancel_reports_failure_not_success(self):
        alice=SimpleNamespace(name='Alice',slug='alice')
        runtime=SimpleNamespace(
            _tr_lower=str.lower,slugify=str.lower,pc_profile=lambda:alice,
            _get_profile=lambda name:alice,requests_state=requests_state,
            events=queue.Queue(),_emit_for=Mock(),
        )
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(requests_state,'_journal',Path(tmp)/'requests.json'), \
             patch.object(requests_state,'_records',{}), \
             patch.object(goal_executor,'cancel_job',
                          side_effect=PermissionError('private owner secret')):
            self.assertTrue(engine_queue.submit(
                runtime,'hedef iptal '+'f'*16,user='Alice',rid='cancel-denied'))
        self.assertIn('iptali doğrulanamadı',
                      runtime._emit_for.call_args.args[2])
        self.assertNotIn('secret',runtime._emit_for.call_args.args[2])
        self.assertTrue(runtime.events.empty())

    def test_answer_to_pending_never_bypasses_core_state_and_engine_loop(self):
        from modules import canonical_goal_flow, brain_entry
        alice=SimpleNamespace(name='Alice',slug='alice')
        runtime=SimpleNamespace(
            _tr_lower=str.lower,slugify=str.lower,pc_profile=lambda:alice,
            _get_profile=lambda name:alice,requests_state=requests_state,
            events=queue.Queue(),_emit_for=Mock(),_record_failure=Mock(),
        )
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(requests_state,'_journal',Path(tmp)/'requests.json'), \
             patch.object(requests_state,'_records',{}), \
             patch.object(canonical_goal_flow,'read_result_command',
                          side_effect=AssertionError('Core answer is not fast read')), \
             patch.object(brain_entry,'fast_lane',return_value=None):
            self.assertTrue(engine_queue.submit(
                runtime,'hedef cevap '+'3'*16+' evet',rid='reply-rid'))
        self.assertEqual(runtime.events.get_nowait(),
                         ('command','hedef cevap '+'3'*16+' evet','yazı','Alice','reply-rid'))
        runtime._emit_for.assert_not_called()
