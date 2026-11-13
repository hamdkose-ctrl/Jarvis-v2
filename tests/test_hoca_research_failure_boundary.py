"""BRAIN-03: typed Hoca research keeps the original domain security boundary.

The retired raw _study_intent handler must never be used to classify a new
lesson. The primary model chooses a Hoca lesson; Core requires explicit,
whole-command research evidence before the existing public-source worker runs.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import brain_core_map, engine_intents, hoca, requests_state


class HocaResearchBoundaryTests(unittest.TestCase):
    COMMAND = "hoca modu: araştır fotosentez"

    def runtime(self):
        return SimpleNamespace(
            profile=SimpleNamespace(data={}, slug="hoca-test"),
            _session=lambda: SimpleNamespace(speech_override=None),
            _record_failure=Mock(),
        )

    def plan(self, text=COMMAND, *, research=True, topic="fotosentez"):
        return brain_core_map.core_plan("hoca.lesson.start", {
            "original_text": text, "topic": topic, "research": research,
        })

    def run_research(self, runtime):
        plan = self.plan()
        self.assertEqual(plan, ("hoca_start", {
            "topic": "fotosentez", "research": True,
        }))
        return engine_intents.dispatch(runtime, *plan,
                                      self.COMMAND, self.COMMAND)

    def test_search_failure_returns_safe_hoca_error_not_raw_fallback(self):
        error = ValueError("public_search_blocked: https://example.test/?key=private-secret")
        runtime = self.runtime()
        with patch("config.load_settings", return_value={"hoca_enabled": True}), \
             patch("modules.requests_state.check"), \
             patch("modules.research_providers.search_public",
                   side_effect=error) as search, \
             patch.object(hoca.llm, "ask") as model:
            reply = self.run_research(runtime)
        self.assertIsInstance(reply, str)
        self.assertIn("Kaynak araması", reply)
        self.assertNotIn("private-secret", reply)
        search.assert_called_once_with("fotosentez")
        model.assert_not_called()
        self.assertIsNone(hoca.active(runtime.profile))

    def test_permission_and_cancellation_propagate(self):
        for error in (PermissionError("denied"), requests_state.Cancelled("stop")):
            with self.subTest(error=type(error).__name__), \
                 patch("config.load_settings", return_value={"hoca_enabled": True}), \
                 patch("modules.requests_state.check"), \
                 patch("modules.research_providers.search_public", side_effect=error), \
                 patch.object(hoca.llm, "ask") as model:
                with self.assertRaises(type(error)):
                    self.run_research(self.runtime())
                model.assert_not_called()

    def test_research_target_requires_exact_original_hoca_user_request(self):
        for utterance in (
            "merhaba", "hoca modu: araştır fotosentez deme",
            "hoca modu: araştır fotosentez?",
            "hoca modu: araştırma yapma", "hoca modu: araştır",
        ):
            with self.subTest(utterance=utterance):
                # A synthetic topic, an extra user instruction or a question
                # cannot grant the model an unrequested public-source fetch.
                self.assertIsNone(self.plan(utterance))
        for invalid in (
            {"original_text": self.COMMAND, "topic": "fotosentez",
             "research": "yes"},
            {"original_text": self.COMMAND, "topic": "fotosentez",
             "research": True, "source": {"url": "https://evil.test"}},
        ):
            self.assertIsNone(brain_core_map.core_plan("hoca.lesson.start", invalid))

    def test_research_source_reaches_only_existing_lesson_worker(self):
        runtime = self.runtime()
        source = {"url": "https://example.test/source", "text": "source text" * 12}
        with patch("config.load_settings", return_value={"hoca_enabled": True}), \
             patch("modules.requests_state.check"), \
             patch.object(hoca, "_research_source", return_value=source) as research, \
             patch.object(hoca, "start",
                          return_value={"topic": "fotosentez", "steps": [{}, {}]}) as start, \
             patch.object(hoca, "_lesson_text", return_value="Kontrol sorusu"):
            reply = self.run_research(runtime)
        research.assert_called_once_with("fotosentez")
        start.assert_called_once_with(runtime.profile, "fotosentez",
                                      level="", source=source)
        self.assertIn(source["url"], reply)


if __name__ == "__main__":
    unittest.main()
