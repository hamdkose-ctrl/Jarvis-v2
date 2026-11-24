"""Çok adımlı görev: anlamadan başlamaz, durunca zinciri keser."""
import threading
import unittest
from unittest.mock import patch

from modules import pc_task


DONE = {"status": "done", "text": "tamam"}


class Planning(unittest.TestCase):
    def test_steps_are_split_on_order_words(self):
        steps = pc_task.split_steps("not defterinde kaydet düğmesine bas, sonra chrome da adres alanına youtube yaz")
        self.assertEqual(len(steps), 2)

    def test_unparsed_step_blocks_the_whole_plan(self):
        result = pc_task.plan("not defterinde kaydet düğmesine bas, sonra hava nasıl")
        self.assertEqual(result["status"], "unparsed")
        self.assertIn("hiçbir şey yapmadım", result["text"])

    def test_too_many_steps_is_refused(self):
        command = ", ".join(["not defterinde kaydet düğmesine bas"] * 8)
        self.assertEqual(pc_task.plan(command)["status"], "too_long")


class WindowInheritance(unittest.TestCase):
    """Zincirin devamında pencereyi tekrar söylemek gerekmez."""

    def test_bare_step_inherits_previous_window(self):
        result = pc_task.plan("hesap makinesinde 7 düğmesine bas, sonra artı düğmesine bas")
        self.assertEqual(result["status"], "ok")
        self.assertEqual([step[2]["window"] for step in result["steps"]],
                         ["hesap makinesi", "hesap makinesi"])

    def test_first_step_still_requires_a_window(self):
        self.assertEqual(pc_task.plan("7 düğmesine bas")["status"], "unparsed")


class Running(unittest.TestCase):
    def test_all_steps_run_in_order(self):
        calls = []
        with patch.object(pc_task.pc_hands, "click", side_effect=lambda w, t: calls.append((w, t)) or DONE), \
             patch.object(pc_task.pc_hands, "type_text", side_effect=lambda w, t, x: calls.append((w, t, x)) or DONE):
            result = pc_task.run("not defterinde kaydet düğmesine bas, sonra chrome da adres alanına youtube yaz")
        self.assertEqual(result["status"], "done")
        self.assertEqual(calls, [("not defteri", "kaydet"), ("chrome", "adres", "youtube")])

    def test_stop_halts_the_rest_of_the_chain(self):
        agenda = {"status": "needs_confirmation", "text": "Onaylıyor musun?"}
        typed = []
        with patch.object(pc_task.pc_hands, "click", return_value=agenda), \
             patch.object(pc_task.pc_hands, "type_text", side_effect=lambda *a: typed.append(a) or DONE):
            result = pc_task.run("not defterinde sil düğmesine bas, sonra chrome da adres alanına youtube yaz")
        self.assertEqual(result["status"], "stop")
        self.assertIn("Onaylıyor musun", result["text"])
        self.assertEqual(typed, [])                 # sonraki adım çalışmadı

    def test_abort_stops_before_first_step(self):
        event = threading.Event(); event.set()
        with patch.object(pc_task.pc_hands, "click") as click:
            result = pc_task.run("not defterinde kaydet düğmesine bas", abort=event)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(click.call_count, 0)

    def test_unparsed_command_does_nothing(self):
        with patch.object(pc_task.pc_hands, "click") as click:
            result = pc_task.run("hava nasıl")
        self.assertEqual(result["status"], "unparsed")
        self.assertEqual(click.call_count, 0)


if __name__ == "__main__":
    unittest.main()


class Recovery(unittest.TestCase):
    """Kurtarma: geçici hata bir kez tekrar denenir, kalıcı hatada dürüstçe durulur."""

    def test_transient_failure_is_retried_once(self):
        calls = []
        def flaky(window, target):
            calls.append(target)
            return {"status": "done", "text": "bastım"} if len(calls) > 1 else {"status": "no_change", "text": "ekran değişmedi"}
        with patch.object(pc_task.pc_hands, "click", side_effect=flaky):
            result = pc_task.run("not defterinde kaydet düğmesine bas")
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(calls), 2)

    def test_persistent_failure_stops_with_two_attempts(self):
        with patch.object(pc_task.pc_hands, "click", return_value={"status": "no_change", "text": "ekran değişmedi"}) as click:
            result = pc_task.run("not defterinde kaydet düğmesine bas")
        self.assertEqual(result["status"], "stop")
        self.assertIn("İki denemede de olmadı", result["text"])
        self.assertEqual(click.call_count, 2)

    def test_missing_target_is_not_retried(self):
        with patch.object(pc_task.pc_hands, "click", return_value={"status": "not_found", "text": "bulamadım"}) as click:
            pc_task.run("not defterinde kaydet düğmesine bas")
        self.assertEqual(click.call_count, 1)
