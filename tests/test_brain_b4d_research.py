import dataclasses
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_core_map, brain_entry, brain_understanding, engine_runtime, requests_state


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

    def assert_research(self, text):
        result = self.understand(text)
        self.assertEqual(result.capability_hint, "research.search", text)
        self.assertEqual(
            dict(result.arguments.get("research", {})),
            {"query": text, "route": "PRIVATE"},
            text,
        )

    def test_plain_arastir_phrase_becomes_research_core_proposal(self):
        self.assert_research("son yapay zeka haberlerini araştır")
        self.assert_research("deprem hakkında araştır")

    def test_bu_hafta_public_research_is_not_rejected_as_deictic(self):
        self.assert_research("bu hafta yapay zeka haberlerini araştır")
        self.assert_research("bu ay teknoloji haberlerini araştır")

    def test_explicit_web_search_forms_are_research(self):
        self.assert_research("yapay zeka haberlerini ara")
        self.assert_research("python eğitimlerini internette bul")

    def test_private_deictic_and_meta_searches_never_get_core_research_args(self):
        for text in (
            "muhasebeden gelen son maili bul",
            "bu dosyada bütçe geçen yerleri bul",
            "bunu internette ara",
            "Bu sitenin iletişim sayfasını bul",
            "izleme listemde en çok düşeni bul",
            "notlarımda toplantıyı bul",
            "araştır ne demek?",
        ):
            result = self.understand(text)
            self.assertNotIn("research", result.arguments, text)
            # The phrase may have its own canonical owner (notes search); it must never become a research task.
            plan = brain_core_map.core_plan(result.capability_hint, result.arguments)
            self.assertNotEqual((plan or ("",))[0], "task", text)

    def test_overlong_or_nul_query_is_not_proposed(self):
        for text in ("haberleri araştır " + "x" * 1100, "haberleri araştır\x00x"):
            result = self.understand(text)
            self.assertFalse(result.arguments.get("research"), text)


class ResearchCoreValidationTests(unittest.TestCase):
    def test_core_revalidates_and_public_claim_is_rejected(self):
        good = {"research": {"query": " deprem haberlerini araştır ", "route": "PRIVATE"}}
        self.assertEqual(
            brain_core_map.core_plan("research.search", good),
            ("task", {"query": "deprem haberlerini araştır", "route": "PRIVATE"}),
        )
        for bad in (
            {},
            {"research": {"query": "x", "route": "PUBLIC"}},
            {"research": {"query": "x"}},
            {"research": {"query": "", "route": "PRIVATE"}},
            {"research": {"query": 5, "route": "PRIVATE"}},
            {"research": {"query": "x" * 1001, "route": "PRIVATE"}},
            {"research": {"query": "x\x00y", "route": "PRIVATE"}},
            {"research": {"query": "x", "route": "PRIVATE", "extra": 1}},
        ):
            self.assertIsNone(brain_core_map.core_plan("research.search", bad), bad)

    def test_no_emitted_hint_is_left_without_a_core_or_named_owner(self):
        self.assertEqual(brain_core_map.LEGACY_OWNED_HINTS, {})
        self.assertEqual(brain_core_map.hint_owner("research.search"), "core:task")
        self.assertIn("research.search", brain_core_map.PARTIAL_CORE_HINTS)


class ResearchEndToEndTests(unittest.TestCase):
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

    def run_text(self, text):
        rid = "b4d-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid), \
             patch("modules.goal_executor.run", return_value="BULGU") as run:
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, handle, run, feedback

    def test_prepare_handoff_runs_explicit_research_through_core_task(self):
        for text in ("son yapay zeka haberlerini araştır", "bu hafta yapay zeka haberlerini araştır"):
            entry, out, handle, run, feedback = self.run_text(text)
            self.assertEqual(entry.understanding.capability_hint, "research.search", text)
            self.assertEqual(out, "BULGU", text)
            run.assert_called_once_with(self.ctx, text)
            self.assertFalse(handle.called, text)
            self.assertEqual(feedback.result_status, "handled")

    def test_brain_query_rewrite_never_becomes_executable_text(self):
        text = "deprem haberlerini araştır"
        rid = "b4d-forge-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid), \
             patch("modules.goal_executor.run", return_value="BULGU") as run:
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            forged = dataclasses.replace(
                entry.understanding,
                arguments={"research": {"query": "başka bir şey", "route": "PRIVATE"}},
            )
            entry = dataclasses.replace(entry, understanding=forged)
            out, _, _ = brain_entry.handoff(self.ctx, entry, Mock(wraps=self.ctx.handle), text)
        self.assertEqual(out, "BULGU")
        run.assert_called_once_with(self.ctx, text)


if __name__ == "__main__":
    unittest.main()
