import unittest
from unittest.mock import patch

from modules import task_workers


class Phase4ComputerReadonlyWiringTests(unittest.TestCase):
    def test_computer_worker_uses_readonly_desktop_observation_and_receipt(self):
        observation = {
            "window": {"app": "calculator", "title": "Calculator"},
            "controls": [{"automation_id": "Display", "name": "19", "type": "Text",
                          "bounds": [0, 0, 20, 20]}],
        }
        task = {
            "id": "observe-1",
            "agent": "computer",
            "input": {"app": "calculator", "operation": "measure"},
            "execution": {"job_id": "job-123"},
        }
        with patch("modules.desktop_agent.run",
                   return_value={"state": "done", "read_only": True,
                                 "observation": observation}) as run:
            result = task_workers.run("alice", task, {})

        run.assert_called_once()
        self.assertTrue(run.call_args.kwargs["read_only"])
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["receipt"]["state"], "observed")
        self.assertEqual(result["receipt"]["capability"]["effect"], "read_only")
        self.assertEqual(result["receipt"]["evidence"]["elements"][0]["name"], "19")


if __name__ == "__main__":
    unittest.main()
