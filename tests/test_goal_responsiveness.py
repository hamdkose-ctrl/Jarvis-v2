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
            with tempfile.TemporaryDirectory() as tmp,patch.object(requests_state,'_journal',Path(tmp)/'requests.json'),patch.object(requests_state,'_records',{}),patch.object(goal_executor,'latest',return_value=None):
                self.assertTrue(engine_queue.submit(runtime,'hedef durumu',user='Alice',rid='status-1'))
                self.assertTrue(runtime.events.empty())
                self.assertEqual(runtime._emit_for.call_args.args,(owner,'assistant','Kayıtlı hedef yok.','yazı'))
                self.assertEqual(runtime._emit_for.call_args.kwargs['rid'],'status-1')
                self.assertFalse(engine_queue.submit(runtime,'hedef durumu',user='Alice',rid='status-1'))
        finally:release.set();thread.join(1)
