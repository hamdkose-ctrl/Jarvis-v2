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

if __name__ == "__main__":
    unittest.main()
