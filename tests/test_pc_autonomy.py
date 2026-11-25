"""Sınırlı otonomi: bütçe, onay kapısı, hesap verebilirlik raporu."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import pc_autonomy


def _plan(*steps):
    return {"status": "ok", "steps": [(text, "pc_click", {"window": "not defteri", "target": text})
                                     for text in steps]}


class Autonomy(unittest.TestCase):
    def test_plan_error_is_reported_without_action(self):
        with patch.object(pc_autonomy.pc_task, "plan", return_value={"status": "unparsed", "text": "anlamadım"}):
            result = pc_autonomy.execute("hava nasıl")
        self.assertEqual(result["status"], "unparsed")

    def test_all_steps_done(self):
        with patch.object(pc_autonomy.pc_task, "plan", return_value=_plan("kaydet")), \
             patch.object(pc_autonomy.pc_task.pc_hands, "click", return_value={"status": "done", "text": "bastım"}):
            result = pc_autonomy.execute("not defterinde kaydet düğmesine bas")
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(result["steps"]), 1)

    def test_confirmation_pauses_autonomy(self):
        with patch.object(pc_autonomy.pc_task, "plan", return_value=_plan("sil")), \
             patch.object(pc_autonomy.pc_task.pc_hands, "click",
                          return_value={"status": "needs_confirmation", "text": "Onaylıyor musun?"}):
            result = pc_autonomy.execute("not defterinde sil düğmesine bas")
        self.assertEqual(result["status"], "paused")
        self.assertIn("onay istiyor", result["text"])

    def test_budget_stops_further_steps(self):
        plan = _plan("bir", "iki", "üç")
        with patch.object(pc_autonomy.pc_task, "plan", return_value=plan), \
             patch.object(pc_autonomy.pc_task.pc_hands, "click", return_value={"status": "done", "text": "ok"}), \
             patch.object(pc_autonomy, "MAX_STEPS", 1):
            result = pc_autonomy.execute("komut", budget=pc_autonomy.Budget(remaining=1))
        self.assertEqual(result["status"], "budget")
        self.assertEqual(len(result["steps"]), 1)

    def test_failure_stops_and_is_recorded(self):
        with patch.object(pc_autonomy.pc_task, "plan", return_value=_plan("kaydet")), \
             patch.object(pc_autonomy.pc_task.pc_hands, "click", return_value={"status": "not_found", "text": "yok"}):
            result = pc_autonomy.execute("not defterinde kaydet düğmesine bas")
        self.assertEqual(result["status"], "stop")
        self.assertEqual(result["steps"][0]["status"], "not_found")

    def test_report_file_is_written(self):
        with patch.object(pc_autonomy, "REPORT_DIR", Path.home() / ".jarvis" / "autonomy-test"), \
             patch.object(pc_autonomy.pc_task, "plan", return_value=_plan("kaydet")), \
             patch.object(pc_autonomy.pc_task.pc_hands, "click", return_value={"status": "done", "text": "ok"}):
            result = pc_autonomy.execute("not defterinde kaydet düğmesine bas")
        path = Path(result["report"])
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "done")
        path.unlink(missing_ok=True)

    def test_abort_before_first_step(self):
        import threading
        event = threading.Event(); event.set()
        with patch.object(pc_autonomy.pc_task, "plan", return_value=_plan("kaydet")), \
             patch.object(pc_autonomy.pc_task.pc_hands, "click") as click:
            result = pc_autonomy.execute("komut", abort=event)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(click.call_count, 0)


if __name__ == "__main__":
    unittest.main()
