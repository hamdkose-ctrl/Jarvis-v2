import unittest

from modules.advisory_router import finalize, prompt_for


class AdvisoryRouterTests(unittest.TestCase):
    def test_direct_answer_is_preserved_when_no_advisory_is_requested(self):
        self.assertEqual(finalize("Bugün hava nasıl?", "Bugün serin.", settings={}), "Bugün serin.")

    def test_decision_json_is_rendered_as_structured_text(self):
        raw = '{"options":[{"name":"A","pros":["hız"],"cons":["maliyet"]},{"name":"B","pros":["ucuz"],"cons":["yavaş"]}],"recommendation":{"option":"A","rationale":"İhtiyaç daha önemli."},"uncertainties":["Bütçe"]}'
        result = finalize("A mı B mi seçeyim?", raw, settings={})
        self.assertIn("Karar analizi:", result)
        self.assertIn("Önerim: A", result)

    def test_non_json_model_answer_falls_back_without_breaking_chat(self):
        raw = "Bence A daha uygun; gerekçesi şu."
        self.assertEqual(finalize("A mı B mi seçeyim?", raw, settings={}), raw)

    def test_prompt_is_only_added_for_explicit_advisory_or_enabled_proactive_mode(self):
        self.assertEqual(prompt_for("Bugün hava nasıl?", {"proactive_suggestions": False}), "")
        self.assertIn("Öneri (risk)", prompt_for("Bugün hava nasıl?", {}))
        self.assertIn("decision_analysis.v1", prompt_for("A mı B mi seçeyim?", {}))
        self.assertIn("proactive_suggestion.v1", prompt_for("Bugün ne yapmalıyım?", {"proactive_suggestions": True}))


if __name__ == "__main__":
    unittest.main()
