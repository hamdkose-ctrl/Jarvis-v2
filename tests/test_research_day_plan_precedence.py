"""Research/news requests must reach canonical routing before calendar/date convenience paths."""
import queue
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dataclasses import replace
import uuid
from test_day_plan import typed_calendar
from test_mail_calendar_fixes import ProfileCase, _runtime
from modules import brain_entry, brain_core_map, main_planner, requests_state
from modules.brain_contracts import RequestKind


REQUEST = (
    "Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır. Eski haberleri atla, "
    "erişilemeyen kaynağı geç, en az iki farklı yayıncıdan doğrulanmış haberleri "
    "kaynak, tarih ve bağlantıyla ver."
)
SHORT_REQUEST = "Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır"


class ResearchDayPlanPrecedenceTests(ProfileCase):
    now = datetime(2026, 10, 28, 11, 30)

    def rt(self):
        rt = _runtime(self, self.profile, self.now)
        rt.google_api.connected = lambda: False
        return rt

    def typed_research(self, runtime, text):
        """A model fixture selects research; real Core prevents calendar capture."""
        owner = runtime.profile.slug
        rid = "research-plan-" + uuid.uuid4().hex[:12]
        assert requests_state.register(owner, rid)
        def model(semantic, utterance, *, active_context=None):
            self.assertEqual(utterance, text)
            return replace(
                semantic, request_kind=RequestKind.CAPABILITY,
                capability_hint="research.search",
                arguments={"original_text": text,
                           "research": {"query": text, "route": "PRIVATE"}},
                needs_input=False, ambiguities=(), actions=(),
                reason_codes=semantic.reason_codes + ("MODEL_DECIDED",))
        with requests_state.activate(owner, rid), \
             patch.object(brain_entry, "apply_model_understanding", side_effect=model):
            entry = brain_entry.prepare(runtime, owner=owner, request_id=rid,
                                        text=text, source="yazı", model_understanding=True)
            out, feedback, _ = brain_entry.handoff(
                runtime, entry,
                Mock(side_effect=AssertionError("typed research entered old NL")), text)
        self.assertEqual(entry.understanding.capability_hint, "research.search")
        self.assertEqual(feedback.result_status, "handled")
        return out

    def test_long_research_request_is_not_swallowed_by_date_or_day_plan(self):
        rt = self.rt()
        rt._daily_briefing = Mock(side_effect=AssertionError("research became daily brief"))
        with patch.object(main_planner, "_day_plan",
                          side_effect=AssertionError("research became day plan")) as day_plan, \
             patch("modules.engine_intents.dispatch", return_value="RESEARCH") as dispatch:
            self.assertEqual(self.typed_research(rt, REQUEST), "RESEARCH")
        day_plan.assert_not_called()
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1], "task")

    def test_short_research_uses_model_selected_closed_core_query(self):
        plan = brain_core_map.core_plan("research.search", {
            "research": {"query": SHORT_REQUEST, "route": "PRIVATE"}})
        self.assertEqual(plan, ("task", {"query": SHORT_REQUEST, "route": "PRIVATE"}))
        with patch("modules.engine_intents.dispatch", return_value="RESEARCH") as dispatch:
            self.assertEqual(self.typed_research(self.rt(), SHORT_REQUEST), "RESEARCH")
        dispatch.assert_called_once()

    def test_explicit_day_plan_requests_still_use_day_plan(self):
        for text in ("Bugünün planı ne?", "Bugün ne yapmalıyım?", "Günümü planla"):
            with self.subTest(text=text):
                self.assertIn("Bugünün planı", typed_calendar(self.rt(), text))

    def test_research_request_does_not_call_day_plan(self):
        rt = self.rt()
        with patch.object(main_planner, "_day_plan") as day_plan, \
             patch("modules.engine_intents.dispatch", return_value="RESEARCH"):
            self.assertEqual(self.typed_research(rt, REQUEST), "RESEARCH")
        day_plan.assert_not_called()

    def test_startup_morning_briefing_path_is_unchanged(self):
        owner = SimpleNamespace(name="Hamdi", slug="hamdi", data={"prefs": {}}, set_pref=Mock())
        runtime = SimpleNamespace(
            profile=SimpleNamespace(name="Ebru", slug="ebru"),
            pc_profile=Mock(return_value=owner),
            datetime=SimpleNamespace(now=lambda: datetime(2026, 10, 28, 9, 0)),
            stop_event=SimpleNamespace(wait=Mock(return_value=False), is_set=Mock(return_value=False)),
            flags={"sleep": False}, _llm=Mock(), _emit_for=Mock(), events=queue.Queue(),
        )
        with patch.object(main_planner, "_daily_briefing", return_value="PC özeti") as briefing, \
                patch.object(main_planner, "_brief_facts", return_value=["PC verisi"]):
            main_planner._morning_brief(runtime)
        briefing.assert_called_once()
        runtime._emit_for.assert_called_once_with(owner, "assistant", "PC özeti")


if __name__ == "__main__":
    unittest.main()
