"""The daily brief hook must never occupy the scheduler thread.

CI evidence (2026-11-17, PR #656 window): with an inline ``_DAILY_NOTIFY()`` the
single ``jarvis-task-queue`` loop sat inside
``engine_background._scheduled_brief`` -> ``outlook.unread_mail`` -> ``sleep(2)``
during the 05-12 UTC morning-brief window and starved goal admission
(``test_canonical_goal_steering`` ``entered.wait(30)`` timeouts). The scheduler
now dispatches the due hook on its own daemon thread; the 60-second throttle,
the single in-flight rule and the recorded-failure channel are unchanged.
"""
import inspect
import threading
import time
import unittest

from modules import task_queue


class DailyNotifyDispatchTests(unittest.TestCase):
    def setUp(self):
        self.saved = (
            task_queue._DAILY_NOTIFY,
            task_queue._DAILY_NEXT,
            task_queue._DAILY_NOTIFY_THREAD,
        )
        task_queue._DAILY_NOTIFY = None
        task_queue._DAILY_NEXT = 0.0
        task_queue._DAILY_NOTIFY_THREAD = None

    def tearDown(self):
        worker = task_queue._DAILY_NOTIFY_THREAD
        if worker is not None and worker.is_alive():
            worker.join(5)
        (
            task_queue._DAILY_NOTIFY,
            task_queue._DAILY_NEXT,
            task_queue._DAILY_NOTIFY_THREAD,
        ) = self.saved

    def _await_hook_thread(self):
        worker = task_queue._DAILY_NOTIFY_THREAD
        self.assertIsNotNone(worker)
        worker.join(5)
        self.assertFalse(worker.is_alive())

    def test_due_hook_runs_on_its_own_thread_not_the_caller(self):
        calls = []
        done = threading.Event()

        def hook():
            calls.append(threading.current_thread().name)
            done.set()

        task_queue._DAILY_NOTIFY = hook
        self.assertTrue(task_queue._dispatch_daily_notify(time.time()))
        self.assertTrue(done.wait(5), 'hook never ran')
        self._await_hook_thread()
        self.assertEqual(calls, ['jarvis-daily-notify'])
        self.assertNotEqual(calls[0], threading.current_thread().name)

    def test_blocking_hook_does_not_delay_the_dispatching_call(self):
        started = threading.Event()
        release = threading.Event()

        def hook():
            started.set()
            release.wait(5)

        task_queue._DAILY_NOTIFY = hook
        began = time.monotonic()
        self.assertTrue(task_queue._dispatch_daily_notify(time.time()))
        elapsed = time.monotonic() - began
        self.assertTrue(started.wait(5), 'hook never started')
        self.assertFalse(started.is_set() and release.is_set())
        self.assertLess(elapsed, 1.0,
                        'dispatch returned only after the hook completed')
        release.set()
        self._await_hook_thread()

    def test_throttle_advances_sixty_seconds_per_fire(self):
        fired = []
        task_queue._DAILY_NOTIFY = lambda: fired.append(1)
        t0 = time.time()
        self.assertTrue(task_queue._dispatch_daily_notify(t0))
        self._await_hook_thread()
        self.assertFalse(task_queue._dispatch_daily_notify(t0))
        self.assertFalse(task_queue._dispatch_daily_notify(t0 + 59.0))
        self.assertTrue(task_queue._dispatch_daily_notify(t0 + 60.0))
        self._await_hook_thread()
        self.assertEqual(fired, [1, 1])

    def test_only_one_hook_thread_runs_at_a_time(self):
        started = threading.Event()
        release = threading.Event()
        count = []

        def hook():
            count.append(1)
            started.set()
            release.wait(5)

        task_queue._DAILY_NOTIFY = hook
        t0 = time.time()
        self.assertTrue(task_queue._dispatch_daily_notify(t0))
        self.assertTrue(started.wait(5))
        self.assertFalse(task_queue._dispatch_daily_notify(t0 + 120.0))
        self.assertEqual(count, [1])
        release.set()
        self._await_hook_thread()

    def test_hook_exception_uses_the_recorded_failure_channel(self):
        recorded = []
        original = task_queue._record_failure
        task_queue._record_failure = lambda context: recorded.append(context)
        try:
            def boom():
                raise RuntimeError('mail kaynağı kilitlendi')

            task_queue._DAILY_NOTIFY = boom
            t0 = time.time()
            self.assertTrue(task_queue._dispatch_daily_notify(t0))
            self._await_hook_thread()
            self.assertEqual(recorded, ['modules/task_queue.py:daily_notify'])
            # A failed fire must not wedge the lane: a later due tick dispatches again.
            task_queue._DAILY_NOTIFY = lambda: recorded.append('second')
            self.assertTrue(task_queue._dispatch_daily_notify(t0 + 120.0))
            self._await_hook_thread()
            self.assertEqual(recorded[-1], 'second')
        finally:
            task_queue._record_failure = original

    def test_no_registered_hook_never_spawns_a_thread(self):
        self.assertFalse(task_queue._dispatch_daily_notify(time.time()))
        self.assertIsNone(task_queue._DAILY_NOTIFY_THREAD)
        self.assertEqual(task_queue._DAILY_NEXT, 0.0)

    def test_set_daily_notify_resets_throttle_and_dispatch_reads_the_fresh_global(self):
        fired = []
        task_queue._DAILY_NEXT = time.time() + 3600
        task_queue.set_daily_notify(lambda: fired.append(1))
        self.assertEqual(task_queue._DAILY_NEXT, 0.0)
        # Scheduler tests neutralize the hook by setting the global to None;
        # dispatch must honor that immediately.
        task_queue._DAILY_NOTIFY = None
        self.assertFalse(task_queue._dispatch_daily_notify(time.time()))
        self.assertEqual(fired, [])

    def test_scheduler_loop_uses_the_off_thread_dispatch(self):
        source = inspect.getsource(task_queue.start)
        self.assertIn('_dispatch_daily_notify(now)', source)
        self.assertNotIn('_DAILY_NOTIFY()', source)


if __name__ == '__main__':
    unittest.main()
