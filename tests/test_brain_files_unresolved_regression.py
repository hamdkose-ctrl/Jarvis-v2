"""Regression (PR488 Windows CI): locate/open file sentences with no resolved reference stay
CAPABILITY (legacy name-search handles them), not CLARIFY. Only Core-owned content operations
(summarize/analyze/translate/convert/compare) ask when unresolved."""
import unittest

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_understanding
from modules.brain_contracts import RequestKind


def understand(text, refs=()):
    return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                          candidates=tuple(refs), references=tuple(refs))


class UnresolvedLocateOpenTests(unittest.TestCase):
    def test_locate_and_open_with_no_reference_stay_capability_not_clarify(self):
        for text in ("dosyayı bul", "dosyayı aç"):
            result = understand(text)
            self.assertEqual(result.request_kind, RequestKind.CAPABILITY, text)
            self.assertEqual(result.capability_hint, "files.read", text)
            self.assertFalse(result.needs_input, text)

    def test_content_operations_with_no_reference_still_ask(self):
        for text in ("dosyayı özetle", "dosyayı analiz et", "dosyayı ingilizceye çevir", "dosyayı pdf'e dönüştür"):
            result = understand(text)
            self.assertEqual(result.request_kind, RequestKind.CLARIFY, text)
            self.assertTrue(result.needs_input, text)


if __name__ == "__main__":
    unittest.main()
