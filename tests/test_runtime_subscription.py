import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import goal_state, goal_state_store, llm, runtime_subscription, service_store


class RuntimeSubscriptionTests(unittest.TestCase):
    def test_source_event_is_persisted_as_goalstate_evidence_and_deduped_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "goal.json"
            goal_state_store.create(state_path, goal_state.new(
                owner="hamdi", job_id="job-1", goal="kaynak değişince bildir",
            ))
            token = llm._key_context.set("hamdi")
            try:
                with patch.object(service_store, "ROOT", root / "service"), patch.object(runtime_subscription, "DATA_DIR", root):
                    subscription_id = runtime_subscription.subscribe(
                        "hamdi", "source:demo", goal_state_path=state_path, job_id="job-1",
                    )
                    payload = {"url": "https://example.test/item", "title": "Yeni kayıt"}
                    accepted = runtime_subscription.publish("hamdi", "source:demo", payload, occurred_at=10)
                    self.assertEqual(accepted, [subscription_id])
                    state = goal_state_store.load(state_path)
                    self.assertEqual(state["version"], 1)
                    self.assertEqual(state["evidence"][0]["kind"], "runtime_event")
                    self.assertEqual(state["evidence"][0]["payload"], payload)
                    self.assertTrue((root / "runtime_events" / "hamdi" / (subscription_id + ".json")).exists())
                    self.assertEqual(runtime_subscription.publish("hamdi", "source:demo", payload, occurred_at=10), [])
                    self.assertEqual(goal_state_store.load(state_path)["version"], 1)
            finally:
                llm._key_context.reset(token)


if __name__ == "__main__":
    unittest.main()
