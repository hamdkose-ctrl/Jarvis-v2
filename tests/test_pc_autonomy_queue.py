"""Otonomi kuyruğu: kapalıyken çalışmaz, bütçe uygular, onayda durur."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import pc_autonomy_queue as q


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "queue.json"
        self.patch_file = patch.object(q, "QUEUE_FILE", self.file)
        self.patch_file.start()

    def tearDown(self):
        self.patch_file.stop()
        self.tmp.cleanup()

    def _state(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def test_disabled_does_not_run(self):
        with patch.object(q.pc_autonomy, "execute") as run:
            result = q.run_due()
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(run.call_count, 0)

    def test_enqueue_then_run(self):
        q.set_enabled(True)
        q.enqueue("not defterinde kaydet düğmesine bas")
        fake = {"status": "done", "text": "tamam", "steps": [1, 2], "report": "r.json"}
        with patch.object(q.pc_autonomy, "execute", return_value=fake) as run:
            result = q.run_due()
        self.assertEqual(result["status"], "done")
        self.assertEqual(run.call_args[0][0], "not defterinde kaydet düğmesine bas")
        self.assertEqual(self._state()["spent_today"], 2)

    def test_daily_budget_blocks_further_runs(self):
        q.set_enabled(True)
        q.enqueue("iş")
        state = self._state(); state["spent_today"] = q.DAILY_STEP_BUDGET; self.file.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(q.pc_autonomy, "execute") as run:
            result = q.run_due()
        self.assertEqual(result["status"], "budget")
        self.assertEqual(run.call_count, 0)

    def test_future_goal_is_not_run_yet(self):
        q.set_enabled(True)
        q.enqueue("ileride", when=time.time() + 3600)
        with patch.object(q.pc_autonomy, "execute") as run:
            self.assertEqual(q.run_due()["status"], "idle")
        self.assertEqual(run.call_count, 0)

    def test_paused_goal_is_not_retried_automatically(self):
        q.set_enabled(True)
        q.enqueue("sil")
        with patch.object(q.pc_autonomy, "execute", return_value={"status": "paused", "text": "onay", "steps": []}):
            q.run_due()
        with patch.object(q.pc_autonomy, "execute") as run:
            self.assertEqual(q.run_due()["status"], "idle")
        self.assertEqual(run.call_count, 0)

    def test_summary_is_honest_when_disabled(self):
        self.assertIn("kapalı", q.summary())


class TickLoop(unittest.TestCase):
    """Otonomi saati: kapalıyken çalışmaz, açıkken kuyruğa bakar, hatada ölmez."""

    def test_disabled_loop_does_not_run(self):
        import threading
        runs = []
        with patch.object(q, "enabled", return_value=False):
            q.tick_loop(threading.Event(), interval=0, runner=lambda abort=None: runs.append(1),
                        sleeper=lambda i: None, max_ticks=2)
        self.assertEqual(runs, [])

    def test_enabled_loop_checks_queue(self):
        import threading
        runs = []
        with patch.object(q, "enabled", return_value=True):
            q.tick_loop(threading.Event(), interval=0,
                        runner=lambda abort=None: runs.append(1) or {"status": "idle"},
                        sleeper=lambda i: None, max_ticks=3)
        self.assertEqual(len(runs), 3)

    def test_loop_survives_errors(self):
        import threading
        runs = []
        def boom(abort=None):
            runs.append(1)
            raise RuntimeError("kuyruk bozuk")
        with patch.object(q, "enabled", return_value=True):
            q.tick_loop(threading.Event(), interval=0, runner=boom, sleeper=lambda i: None, max_ticks=2)
        self.assertEqual(len(runs), 2)         # hata döngüyü öldürmedi


if __name__ == "__main__":
    unittest.main()
