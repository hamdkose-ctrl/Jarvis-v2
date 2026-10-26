import unittest
from unittest.mock import Mock, patch
from datetime import datetime

from modules import task_queue
from modules.cron_schedule import CronExpression


class CronExpressionTests(unittest.TestCase):
    def test_matches_standard_five_field_expression(self):
        cron = CronExpression("*/15 9-17 * * 1-5")
        self.assertTrue(cron.matches(datetime(2026, 10, 26, 9, 0)))   # Monday
        self.assertTrue(cron.matches(datetime(2026, 10, 26, 17, 45)))
        self.assertFalse(cron.matches(datetime(2026, 10, 26, 18, 0)))
        self.assertFalse(cron.matches(datetime(2026, 10, 25, 9, 0)))  # Sunday

    def test_supports_lists_ranges_and_step_values(self):
        cron = CronExpression("5,20-25/5 8 * 1,6 *")
        self.assertTrue(cron.matches(datetime(2026, 1, 1, 8, 5)))
        self.assertTrue(cron.matches(datetime(2026, 6, 1, 8, 25)))
        self.assertFalse(cron.matches(datetime(2026, 2, 1, 8, 5)))

    def test_rejects_invalid_cron_expression(self):
        with self.assertRaises(ValueError):
            CronExpression("* * * *")
        with self.assertRaises(ValueError):
            CronExpression("61 * * * *")

    def test_next_run_is_after_reference(self):
        cron = CronExpression("*/15 * * * *")
        self.assertEqual(
            cron.next_after(datetime(2026, 10, 26, 10, 1)),
            datetime(2026, 10, 26, 10, 15),
        )

    @patch("modules.task_agents.validate")
    @patch("modules.task_queue.service_store.database")
    def test_enqueue_persists_cron_without_model_planning(self, database, validate):
        db = Mock()
        database.return_value.__enter__.return_value = db
        task_queue.enqueue(
            "hamdi",
            [{"id": "check", "agent": "verify", "depends": [], "input": {}}],
            "modelsiz kontrol",
            cron="*/10 * * * *",
        )
        args = db.execute.call_args_list[-1].args
        self.assertIn("cron", args[0])
        self.assertEqual(args[1][-1], "*/10 * * * *")
        validate.assert_called_once()

    @patch("modules.task_queue.service_store.database")
    def test_run_now_moves_queued_job_to_current_time(self, database):
        db = Mock()
        database.return_value.__enter__.return_value = db
        db.execute.return_value.fetchone.return_value = {"state": "queued", "job_id": "old-job"}
        self.assertEqual(task_queue.run_now("hamdi", "queue-id"), "queue-id")
        sql, params = db.execute.call_args_list[-1].args
        self.assertIn("due=?", sql)
        self.assertEqual(params[2], "old-job")
    @patch("modules.task_queue.service_store.database")
    def test_run_now_refuses_cancelled_job(self, database):
        db = Mock()
        database.return_value.__enter__.return_value = db
        db.execute.return_value.fetchone.return_value = {"state": "cancelled", "job_id": "old-job"}
        with self.assertRaises(ValueError):
            task_queue.run_now("hamdi", "queue-id")
        self.assertEqual(len(db.execute.call_args_list), 1)

    def test_render_rows_uses_real_line_breaks_and_run_now_hint(self):
        text = task_queue.render_rows([{
            "id": "a" * 16, "state": "queued", "due": 0, "job_id": "j1", "error": "",
            "repeat_seconds": 0, "last_job_id": "", "cron": "0 9 * * 1-5", "instruction": "sabah raporu",
        }])
        self.assertNotIn("\\n", text)
        self.assertIn("\nCron: 0 9 * * 1-5", text)
        self.assertIn("kuyruk çalıştır " + "a" * 16, text)


class CronChatCommandTests(unittest.TestCase):
    @patch("modules.task_queue.enqueue_script", return_value="b" * 16)
    @patch("modules.task_agents.llm.ask")
    def test_script_cron_command_skips_model(self, ask, enqueue_script):
        from modules import task_agents
        reply = task_agents.handle(
            "hamdi",
            'görev betik */30 * * * *: {"instruction": "kontrol", "tasks": '
            '[{"id": "check", "agent": "verify", "depends": [], "input": {}}]}',
        )
        ask.assert_not_called()
        owner, tasks, instruction, cron = enqueue_script.call_args.args
        self.assertEqual((owner, instruction, cron), ("hamdi", "kontrol", "*/30 * * * *"))
        self.assertEqual(tasks[0]["agent"], "verify")
        self.assertIn("kuyruk çalıştır " + "b" * 16, reply)

    @patch("modules.task_queue.enqueue", return_value="c" * 16)
    @patch("modules.task_agents.llm.ask",
           return_value='{"tasks": [{"id": "r", "agent": "research", "depends": [], "input": {}}]}')
    def test_cron_command_plans_once_and_stores_expression(self, ask, enqueue):
        from modules import task_agents
        reply = task_agents.handle("hamdi", "görev cron 0 9 * * 1-5: sabah haber özeti")
        ask.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["cron"], "0 9 * * 1-5")
        self.assertEqual(enqueue.call_args.args[2], "sabah haber özeti")
        self.assertIn("Cron: 0 9 * * 1-5", reply)

    @patch("modules.task_queue.run_now")
    def test_run_now_chat_command(self, run_now):
        from modules import task_agents
        reply = task_agents.handle("hamdi", "kuyruk çalıştır " + "d" * 16)
        run_now.assert_called_once_with("hamdi", "d" * 16)
        self.assertIn("temiz", reply)

if __name__ == "__main__":
    unittest.main()
