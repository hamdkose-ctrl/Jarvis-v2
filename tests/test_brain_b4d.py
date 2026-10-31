"""PR7 Closeout-B4d: research.search -> Core `research` (validated query, route PRIVATE); LEGACY_OWNED_HINTS boş."""
import dataclasses
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_core_map, brain_entry, brain_understanding, engine_runtime, requests_state


class UnderstandingTests(unittest.TestCase):
    def understand(self, text):
        return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                              candidates=(), references=())

    def test_research_hint_carries_the_users_own_query_with_private_route(self):
        r = self.understand("internette ara")
        self.assertEqual(r.capability_hint, "research.search")
        self.assertEqual(dict(r.arguments["research"]), {"query": "internette ara", "route": "PRIVATE"})

    def test_overlong_request_gets_no_proposal(self):
        r = self.understand("internette ara " + "x" * 1100)
        self.assertNotIn("research", r.arguments)

    def test_only_explicit_public_web_research_is_proposed(self):
        for text in ("yapay zeka haberlerini ara", "python eğitimlerini internette bul", "deprem hakkında araştır ve bul"):
            self.assertIn("research", self.understand(text).arguments, text)
        for text in ("muhasebeden gelen son maili bul", "bu dosyada “bütçe” geçen yerleri bul", "bunu internette ara benzerlerini de bul",
                     "Bu sitenin iletişim sayfasını bul.", "izleme listemde en çok düşeni bul", "notlarımda toplantıyı bul",
                     "Ben “bunu ara” dersem sen neyi aradığımı nasıl anlarsın?"):
            r = self.understand(text)
            self.assertNotIn("research", r.arguments, text)


class CoreValidationTests(unittest.TestCase):
    def test_core_revalidates_and_never_accepts_a_public_claim(self):
        good = {"research": {"query": "  deprem haberlerini ara ", "route": "PRIVATE"}}
        self.assertEqual(brain_core_map.core_plan("research.search", good),
                         ("research", {"query": "deprem haberlerini ara", "route": "PRIVATE"}))
        for bad in ({}, {"research": {"query": "x", "route": "PUBLIC"}}, {"research": {"query": "x"}},
                    {"research": {"query": "", "route": "PRIVATE"}}, {"research": {"query": 5, "route": "PRIVATE"}},
                    {"research": {"query": "x" * 1001, "route": "PRIVATE"}},
                    {"research": {"query": "x", "route": "PRIVATE", "extra": 1}}):
            self.assertIsNone(brain_core_map.core_plan("research.search", bad), bad)

    def test_no_hint_is_left_without_a_core_intent(self):
        self.assertEqual(brain_core_map.LEGACY_OWNED_HINTS, {})
        self.assertEqual(brain_core_map.hint_owner("research.search"), "core:research")
        self.assertIn("research.search", brain_core_map.PARTIAL_CORE_HINTS)   # mail/file/page asks stay legacy, said openly


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)

    def prepare(self, text):
        rid = "b4d-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        return rid, text

    def run_real(self, text):
        rid, _ = self.prepare(text)
        with requests_state.activate(self.owner, rid), patch("modules.goal_executor.run", return_value="BULGU") as run:
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, handle, run

    SENTENCES = ("yapay zeka haberlerini ara", "python eğitimlerini internette bul", "deprem hakkında araştır ve bul")

    def test_real_claim_prepare_handoff_runs_goal_executor_through_core_research(self):
        for text in self.SENTENCES:
            entry, out, handle, run = self.run_real(text)
            self.assertEqual(entry.understanding.capability_hint, "research.search", text)
            self.assertEqual(out, "BULGU", text)
            self.assertEqual(run.call_args[0][1], text)
            self.assertFalse(handle.called, text)

    def test_front_gate_web_search_still_beats_core_research(self):
        # Honest scope: "internette ... ara" is answered by the existing front gate before any Core plan.
        entry, out, handle, run = self.run_real("internette deprem haberlerini ara")
        self.assertEqual(entry.understanding.capability_hint, "research.search")
        self.assertIn("tarayıcıda arama açtım", out)
        run.assert_not_called()

    def test_rewritten_query_never_reaches_core(self):
        rid, text = self.prepare("internette deprem haberlerini ara")
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            self.assertEqual(brain_entry.core_plan(entry)[0], "research")
            forged = dataclasses.replace(entry.understanding, arguments={"research": {"query": "başka şey", "route": "PRIVATE"}})
            self.assertIsNone(brain_entry.core_plan(dataclasses.replace(entry, understanding=forged)))


if __name__ == "__main__":
    unittest.main()
