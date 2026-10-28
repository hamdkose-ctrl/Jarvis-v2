"""Research/news requests must reach canonical routing before calendar/date convenience paths."""
import queue
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_mail_calendar_fixes import ProfileCase, _runtime, say
from modules import main_planner, router


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

    def test_long_research_request_is_not_swallowed_by_date_or_day_plan(self):
        rt = self.rt()
        rt.route = Mock(return_value={"intent": "task", "args": {"request": REQUEST}})
        rt._daily_briefing = Mock(side_effect=AssertionError("research daily briefing'e gitmemeli"))
        with patch.object(main_planner, "_day_plan", side_effect=AssertionError("research _day_plan'a gitmemeli")), \
                patch("modules.engine_intents.dispatch", return_value="RESEARCH") as dispatch:
            self.assertEqual(rt.handle(REQUEST), "RESEARCH")
        rt.route.assert_called_once_with(REQUEST)
        dispatch.assert_called_once()

    def test_short_news_research_request_reaches_deterministic_research_classification(self):
        result = router.classify(SHORT_REQUEST, lambda *_: (_ for _ in ()).throw(AssertionError("deterministic research route model istememeli")))
        self.assertEqual(result["intent"], "task")
        self.assertEqual(result["args"]["request"], SHORT_REQUEST)

    def test_explicit_day_plan_requests_still_use_day_plan(self):
        for text in ("Bugünün planı ne?", "Bugün ne yapmalıyım?", "Günümü planla"):
            with self.subTest(text=text):
                self.assertIn("Bugünün planı", say(self.rt(), text))

    def test_research_request_does_not_call_day_plan(self):
        rt = self.rt()
        rt.route = Mock(return_value={"intent": "task", "args": {"request": REQUEST}})
        with patch.object(main_planner, "_day_plan") as day_plan, \
                patch("modules.engine_intents.dispatch", return_value="RESEARCH"):
            self.assertEqual(rt.handle(REQUEST), "RESEARCH")
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
