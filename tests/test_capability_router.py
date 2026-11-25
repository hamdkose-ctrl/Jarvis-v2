"""Tek beyin: karar tek yerde, kelime tabanlı çoklu beyin yok."""
import unittest
from unittest.mock import patch

from modules import capability_router as router


class SingleBrain(unittest.TestCase):
    def test_semantic_decision_wins_when_model_understands(self):
        meaning = {"status": "ok", "capability": "pc_open_site", "slots": {"text": "youtube.com"},
                   "confidence": 0.9}
        with patch("modules.capability_llm.resolve", return_value=meaning):
            result = router.route("şu videolara bakak bi")
        self.assertEqual((result["status"], result["source"]), ("run", "brain"))

    def test_offline_fallback_only_when_model_fails(self):
        with patch("modules.capability_llm.resolve", return_value={"status": "uncertain"}):
            result = router.route("youtube aç")
        self.assertEqual((result["status"], result["source"]), ("run", "offline"))

    def test_unknown_request_does_nothing(self):
        with patch("modules.capability_llm.resolve", return_value={"status": "uncertain"}):
            result = router.route("dün akşam ne yedim")
        self.assertEqual(result["status"], "none")

    def test_missing_slot_becomes_question(self):
        meaning = {"status": "need", "capability": "pc_type", "slots": {}, "missing": ["text"]}
        with patch("modules.capability_llm.resolve", return_value=meaning):
            result = router.route("şuraya bir şey yaz")
        self.assertEqual((result["status"], result["missing"]), ("ask", ["text"]))

    def test_context_is_passed_to_the_single_brain(self):
        meaning = {"status": "ok", "capability": "pc_save", "slots": {"name": "notlar"}, "confidence": 0.8}
        with patch("modules.capability_llm.resolve", return_value=meaning) as brain:
            router.route("bunu kaydet", {"window": "Adsız - Not Defteri"})
        self.assertEqual(brain.call_args.kwargs["context"]["window"], "Adsız - Not Defteri")


if __name__ == "__main__":
    unittest.main()
