import unittest

import test_brain_production_entry as fx
from modules import brain_understanding


class ResearchUnderstandingRegressionTests(unittest.TestCase):
    def understand(self, text):
        return brain_understanding.understand(
            owner=fx.OWNER,
            request_id=fx.RID,
            text=text,
            active_context=fx.context(),
            candidates=(),
            references=(),
        )

    def test_plain_arastir_phrase_becomes_research_core_proposal(self):
        result = self.understand("son yapay zeka haberlerini araştır")
        self.assertEqual(result.capability_hint, "research.search")
        self.assertEqual(
            dict(result.arguments.get("research", {})),
            {"query": "son yapay zeka haberlerini araştır", "route": "PRIVATE"},
        )

    def test_bu_hafta_public_research_is_not_rejected_as_deictic(self):
        text = "bu hafta yapay zeka haberlerini araştır"
        result = self.understand(text)
        self.assertEqual(result.capability_hint, "research.search")
        self.assertEqual(
            dict(result.arguments.get("research", {})),
            {"query": text, "route": "PRIVATE"},
        )


if __name__ == "__main__":
    unittest.main()
