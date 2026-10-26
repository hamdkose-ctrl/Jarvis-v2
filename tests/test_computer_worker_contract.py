import unittest

from modules import computer_worker_contract as worker


class ComputerWorkerContractTests(unittest.TestCase):
    def test_only_pilot_apps_are_allowed(self):
        self.assertTrue(worker.app_allowed("Calculator"))
        self.assertTrue(worker.app_allowed("notepad"))
        self.assertFalse(worker.app_allowed("powershell"))

    def test_uia_measurement_is_metadata_only_and_bounded(self):
        result = worker.measure_uia([
            {"automation_id": "Display", "name": "19", "control_type": "Text", "bounds": [0, 0, 20, 20]}
        ])
        self.assertEqual(result["state"], "observed")
        self.assertEqual(result["elements"][0]["name"], "19")

    def test_capability_and_receipt_are_explicit(self):
        capability = worker.capability("Calculator", "observe")
        self.assertEqual(capability["effect"], "read_only")
        receipt = worker.receipt("job-1", capability, "observed", evidence={"window": "Calculator"})
        self.assertEqual(receipt["state"], "observed")
        self.assertEqual(receipt["evidence"]["window"], "Calculator")

    def test_effectful_or_unlisted_requests_fail_closed(self):
        with self.assertRaises(worker.ComputerWorkerContractError):
            worker.capability("Calculator", "type")
        with self.assertRaises(worker.ComputerWorkerContractError):
            worker.capability("powershell", "observe")


if __name__ == "__main__":
    unittest.main()
