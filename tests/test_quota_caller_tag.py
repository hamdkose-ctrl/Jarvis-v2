"""Kota kaydındaki 's' etiketi: çağrı sahibi açıkça verilir, yığın taramasına güvenilmez.

Canlı ölçüm (26 Kasım): isteklerin %23,8'i "bilinmiyor" görünüyordu; hangi adımın kotayı
yaktığı bilinmiyordu. Bu yüzden `run_request` çağrı sahibini etiketler.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modules import smart_router, usage_meter


class Scope(unittest.TestCase):
    def test_scope_overrides_stack_scan(self):
        with usage_meter.caller_scope("brain_model_understanding.propose"):
            self.assertEqual(usage_meter.caller(), "brain_model_understanding.propose")

    def test_scope_is_restored(self):
        with usage_meter.caller_scope("x.y"):
            pass
        self.assertNotEqual(usage_meter.caller(), "x.y")

    def test_record_uses_the_scope_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(usage_meter, "_dir", lambda: folder), \
                 mock.patch.object(usage_meter, "_owner", lambda: "testkota"), \
                 usage_meter.caller_scope("engine_intents.dispatch"):
                usage_meter.record("gemini", "m", 10, 5)
            row = json.loads((folder / "testkota.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["s"], "engine_intents.dispatch")


class CallSite(unittest.TestCase):
    def test_label_names_the_calling_function(self):
        def fake_run():
            return smart_router._callsite_label()

        def cafe():
            return fake_run()

        self.assertEqual(cafe(), "test_quota_caller_tag.cafe")

    def test_run_request_labels_the_call_without_network(self):
        seen = {}

        def fake_owned(request, adapter, *, validator=None):
            seen["label"] = usage_meter.caller()
            return "ok"

        request = smart_router.ModelRequest(owner="test", request_id="r1",
                                            profile="brain_understanding",
                                            data_scope="conversation",
                                            work_class="interactive")
        with mock.patch.object(smart_router, "_run_owned_request", fake_owned),              mock.patch.object(smart_router.requests_state, "request_identity", lambda owner: None),              mock.patch("modules.llm.owner_context", __import__("contextlib").nullcontext):
            smart_router.run_request(request, lambda spec: "x")
        self.assertEqual(seen["label"], "test_quota_caller_tag.test_run_request_labels_the_call_without_network")

    def test_request_field_exists(self):
        self.assertIn("caller", smart_router.ModelRequest.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
