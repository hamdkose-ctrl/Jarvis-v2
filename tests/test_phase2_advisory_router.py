import unittest

from modules import advisory_router, brain_entry
from test_brain_pr8b_advisor_echo import entry

DECISION_JSON = ('{"options":[{"name":"A","pros":["hız"],"cons":["maliyet"]},'
                 '{"name":"B","pros":["ucuz"],"cons":["yavaş"]}],'
                 '"recommendation":{"option":"A","rationale":"İhtiyaç daha önemli."},'
                 '"uncertainties":["Bütçe"]}')


class AdvisoryRouterTests(unittest.TestCase):
    def test_direct_answer_is_preserved_when_no_advisory_is_requested(self):
        with brain_entry.bind(entry("Bugün hava nasıl?")):
            self.assertEqual(advisory_router.finalize("Bugün hava nasıl?", "Bugün serin.", settings={}), "Bugün serin.")

    def test_decision_json_is_rendered_as_structured_text(self):
        with brain_entry.bind(entry("A mı B mi seçeyim?")):
            result = advisory_router.finalize("A mı B mi seçeyim?", DECISION_JSON, settings={})
        self.assertIn("Karar analizi:", result)
        self.assertIn("Önerim: A", result)

    def test_non_json_model_answer_falls_back_without_breaking_chat(self):
        raw = "Bence A daha uygun; gerekçesi şu."
        with brain_entry.bind(entry("A mı B mi seçeyim?")):
            self.assertEqual(advisory_router.finalize("A mı B mi seçeyim?", raw, settings={}), raw)

    def test_prompt_is_only_added_for_explicit_advisory_or_enabled_proactive_mode(self):
        with brain_entry.bind(entry("Bugün hava nasıl?")):
            self.assertEqual(advisory_router.prompt_for("Bugün hava nasıl?", {"proactive_suggestions": False}), "")
            self.assertIn("Öneri (risk)", advisory_router.prompt_for("Bugün hava nasıl?", {}))
        with brain_entry.bind(entry("A mı B mi seçeyim?")):
            self.assertIn("decision_analysis.v1", advisory_router.prompt_for("A mı B mi seçeyim?", {}))
        with brain_entry.bind(entry("Bugün ne yapmalıyım?")):
            self.assertIn("proactive_suggestion.v1", advisory_router.prompt_for("Bugün ne yapmalıyım?", {"proactive_suggestions": True}))


if __name__ == "__main__":
    unittest.main()
