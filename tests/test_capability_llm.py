"""Model destekli anlam: yalnız doğrulanmış yetenek/alan kabul edilir."""
import json
import unittest
from unittest.mock import patch

from modules import capability_llm as brain_llm


def answer(payload):
    return json.dumps(payload, ensure_ascii=False)


class Validation(unittest.TestCase):
    def setUp(self):
        brain_llm._cache.clear()

    def _resolve(self, payload, text="şu işi hallet"):
        with patch.object(brain_llm, "_ask_model", return_value=answer(payload)):
            return brain_llm.resolve(text)

    def test_unknown_capability_is_rejected(self):
        result = self._resolve({"capability": "system_reboot", "slots": {}, "confidence": 0.9})
        self.assertEqual(result["status"], "uncertain")

    def test_known_capability_with_slots_is_ok(self):
        result = self._resolve({"capability": "pc_type",
                                "slots": {"window": "chrome", "text": "hava durumu"},
                                "confidence": 0.9})
        self.assertEqual((result["status"], result["capability"]), ("ok", "pc_type"))
        self.assertEqual(result["slots"]["text"], "hava durumu")

    def test_missing_slot_becomes_a_question(self):
        result = self._resolve({"capability": "pc_type", "slots": {"window": "chrome"}, "confidence": 0.9})
        self.assertEqual(result["status"], "need")
        self.assertEqual(result["missing"], ["text"])

    def test_nonexistent_path_is_dropped(self):
        result = self._resolve({"capability": "file_read",
                                "slots": {"path": "/kesinlikle/yok.txt"}, "confidence": 0.9})
        self.assertEqual(result["status"], "need")
        self.assertEqual(result["missing"], ["path"])

    def test_low_confidence_is_ignored(self):
        result = self._resolve({"capability": "pc_type", "slots": {"text": "x"}, "confidence": 0.2})
        self.assertEqual(result["status"], "uncertain")

    def test_broken_json_is_safe(self):
        with patch.object(brain_llm, "_ask_model", return_value="anlamadım"):
            self.assertEqual(brain_llm.resolve("şunu yap")["status"], "uncertain")

    def test_model_failure_is_safe(self):
        with patch.object(brain_llm, "_ask_model", return_value=None):
            self.assertEqual(brain_llm.resolve("şunu yap")["status"], "uncertain")

    def test_cache_prevents_second_call(self):
        payload = {"capability": "screen_summary", "slots": {}, "confidence": 0.9}
        with patch.object(brain_llm, "_ask_model", return_value=answer(payload)) as ask:
            brain_llm.resolve("ekranda ne var acaba")
            brain_llm.resolve("ekranda ne var acaba")
        self.assertEqual(ask.call_count, 1)


if __name__ == "__main__":
    unittest.main()
