"""PR8b: Advisor semantic selection moves to canonical Understanding; EchoPreview becomes grounded presentation.

Both slices stay proposal/presentation only. Advisor may not dispatch, permit or complete;
EchoPreview may not be read as approval, effect receipt, execution or completion.
"""
from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import advisory_router, brain_echo, brain_entry, brain_understanding, critique_advisor, decision_advisor, guidance_advisor
from modules import engine_live_brain, engine_loop
from modules.brain_contracts import ActiveContext, ContextReference
from modules.brain_gates import GateObservation

OWNER = "hamdi"
RID = "req-pr8b"
ROOT = Path(__file__).resolve().parent.parent

DECISION_JSON = ('{"options":[{"name":"Evden","pros":["odak"],"cons":["yol"]},'
                 '{"name":"Ofisten","pros":["ekip"],"cons":["trafik"]}],'
                 '"recommendation":{"option":"Evden","rationale":"Bugünkü odak ihtiyacı ön planda."},'
                 '"uncertainties":["Ev koşulları"]}')
CRITIQUE_JSON = '{"weak_point":"Kapsam çok geniş.","because":"İlk teslim sınırı tanımsız.",' \
                '"impact":"İlerlemeyi ölçmek zorlaşır.","next_step":"Tek doğrulanabilir hedef seç."}'
GUIDANCE_JSON = '{"objective":"Yer imlerini dışa aktarmak.","steps":[{"action":"Menüyü aç","why":"Panel orada",' \
                '"risks":[],"watchouts":[]}]}'


def semantic(text: str, references: tuple[ContextReference, ...] = ()):
    return brain_understanding.understand(
        owner=OWNER, request_id=RID, text=text,
        active_context=ActiveContext(owner=OWNER, request_id=RID),
        candidates=references, references=references,
    )


def entry(text: str, references: tuple[ContextReference, ...] = ()) -> brain_entry.EntryResult:
    return brain_entry.EntryResult(
        owner=OWNER, request_id=RID, source="yazı", text=text,
        active_context=ActiveContext(owner=OWNER, request_id=RID),
        state_gate=GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH"),
        fast_gate=GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH"),
        candidates=references, references=references,
        understanding=semantic(text, references),
    )


def file_reference(name: str) -> ContextReference:
    return ContextReference(
        id=f"file:nxapi.file_inventory:C:/Users/hamdi/Belgeler/{name}",
        kind="file", source="nxapi.file_inventory", owner=OWNER,
        provenance={"path": f"C:/Users/hamdi/Belgeler/{name}"},
    )


class AdvisorCanonicalSelectionTests(unittest.TestCase):
    def test_advisory_mode_is_a_canonical_understanding_argument(self):
        self.assertEqual(semantic("Evden mi ofisten mi çalışayım?").arguments.get("advisory"), "decision")
        self.assertEqual(semantic("Bu planı dürüstçe eleştir.").arguments.get("advisory"), "critique")
        self.assertEqual(semantic("Bu işi adım adım anlat.").arguments.get("advisory"), "guidance")
        self.assertIsNone(semantic("Bugün hava nasıl?").arguments.get("advisory"))

    def test_decision_output_is_reached_through_canonical_understanding(self):
        with brain_entry.bind(entry("Evden mi ofisten mi çalışayım?")):
            self.assertIn("decision_analysis.v1",
                          advisory_router.prompt_for("Evden mi ofisten mi çalışayım?", {"proactive_suggestions": False}))
            self.assertIn("Karar analizi:",
                          advisory_router.finalize("Evden mi ofisten mi çalışayım?", DECISION_JSON, settings={}))

    def test_critique_and_guidance_output_reach_through_canonical_understanding(self):
        for text, payload, marker in (
            ("Bu planı dürüstçe eleştir.", CRITIQUE_JSON, "Kapsam çok geniş."),
            ("Bu işi adım adım anlat.", GUIDANCE_JSON, "Uygulama rehberi:"),
        ):
            with self.subTest(text=text), brain_entry.bind(entry(text)):
                self.assertIn("Şema adı", advisory_router.prompt_for(text, {"proactive_suggestions": False}))
                self.assertIn(marker, advisory_router.finalize(text, payload, settings={}))

    def test_legacy_regex_selectors_are_removed_after_caller_zero(self):
        for module in (decision_advisor, critique_advisor, guidance_advisor):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, "requested"),
                                 "Doğal dil seçimi canonical Understanding'e taşındı; legacy selector kalamaz.")
        source = (ROOT / 'modules' / 'advisory_router.py').read_text(encoding='utf-8')
        self.assertNotIn("requested(", source)
        self.assertNotIn("def _mode(command", source)

    def test_raw_command_is_not_reinterpreted_when_canonical_result_has_no_advisory(self):
        with brain_entry.bind(entry("Bugün hava nasıl?")):
            self.assertNotIn("decision_analysis.v1",
                             advisory_router.prompt_for("Evden mi ofisten mi çalışayım?", {"proactive_suggestions": False}))
            self.assertNotIn("Karar analizi:",
                             advisory_router.finalize("Evden mi ofisten mi çalışayım?", DECISION_JSON, settings={}))

    def test_nested_step_text_does_not_borrow_another_utterances_advisory_mode(self):
        with brain_entry.bind(entry("önce notları özetle")):
            self.assertEqual(advisory_router.prompt_for("A mı B mi seçeyim?", {"proactive_suggestions": False}), "")


class AdvisorKeepsCanonicalContextTests(unittest.TestCase):
    def test_advisor_uses_the_bound_entry_without_running_understanding_again(self):
        with brain_entry.bind(entry("Evden mi ofisten mi çalışayım?")), patch.object(
                brain_understanding, "understand", side_effect=AssertionError("İkinci understanding çağrılamaz")):
            self.assertIn("decision_analysis.v1",
                          advisory_router.prompt_for("Evden mi ofisten mi çalışayım?", {"proactive_suggestions": False}))

    def test_advisor_reads_no_history_reference_or_profile_truth_source(self):
        source = (ROOT / 'modules' / 'advisory_router.py').read_text(encoding='utf-8')
        for legacy in ("history", "brain_context", "brain_reference", "build_candidates", "resolve_references",
                       "profile_tr", "memory"):
            self.assertNotIn(legacy, source, f"Advisor ikinci bir context kaynağı kuramaz: {legacy}.")


class EchoPreviewCanonicalSourceTests(unittest.TestCase):
    def test_preview_comes_from_bounded_semantic_arguments_and_resolved_reference(self):
        references = (file_reference("2024-finans-raporu.pdf"),)
        result = semantic("2024-finans-raporu.pdf dosyasını Excel'e dönüştür", references)
        self.assertIsNotNone(result.preview)
        self.assertIn("2024-finans-raporu.pdf", result.preview.text)
        self.assertIn("Excel", result.preview.text)
        self.assertNotEqual(result.preview.text, "2024-finans-raporu.pdf dosyasını Excel'e dönüştür")

    def test_preview_never_reenters_legacy_resolvers_or_routers(self):
        source = (ROOT / 'modules' / 'brain_echo.py').read_text(encoding='utf-8')
        for legacy in ("re.compile", "router", "_resolve_doc", "chat_translation", "advisory"):
            self.assertNotIn(legacy, source, f"Echo kendi başına metin yorumlayamaz: {legacy}.")

    def test_preview_is_not_permission_approval_effect_execution_or_completion(self):
        result = semantic("2024-finans-raporu.pdf dosyasını Excel'e dönüştür", (file_reference("2024-finans-raporu.pdf"),))
        payload = result.preview.to_dict()
        self.assertEqual(set(payload) - {"reason_code"}, {"text"})
        for authority in ("permission", "approved", "authorized", "execute", "completed", "done", "effect_allowed"):
            self.assertNotIn(authority, str(payload).casefold())

    def test_preview_presentation_touches_no_core_handler_tool_worker_or_effect(self):
        runtime = SimpleNamespace(
            emit=Mock(),
            handle=Mock(side_effect=AssertionError("Echo Core'u çalıştıramaz")),
            _session=Mock(side_effect=AssertionError("Echo state yazamaz")),
        )
        result = entry("2024-finans-raporu.pdf dosyasını Excel'e dönüştür", (file_reference("2024-finans-raporu.pdf"),))
        with patch("modules.engine_intents.dispatch", side_effect=AssertionError("Echo dispatch edemez")):
            brain_echo.present(runtime, result)
        runtime.emit.assert_called_once()
        self.assertEqual(runtime.emit.call_args.args[0], "activity")
        self.assertIn("2024-finans-raporu.pdf", runtime.emit.call_args.args[2])


class OrdinaryChatUnchangedTests(unittest.TestCase):
    def test_plain_chat_has_no_preview_and_no_extra_message(self):
        runtime = SimpleNamespace(emit=Mock())
        for text in ("Merhaba", "2+2 kaç eder?", "Nasılsın?"):
            with self.subTest(text=text):
                result = semantic(text)
                self.assertIsNone(result.preview)
                self.assertIsNone(result.arguments.get("advisory"))
                brain_echo.present(runtime, entry(text))
        runtime.emit.assert_not_called()

    def test_plain_chat_finalizer_still_returns_the_direct_answer(self):
        with brain_entry.bind(entry("Bugün hava nasıl?")):
            self.assertEqual(advisory_router.finalize("Bugün hava nasıl?", "Bugün serin.", settings={}), "Bugün serin.")

    def test_echo_presentation_is_wired_after_the_canonical_entry(self):
        for module, function in ((engine_loop, engine_loop.main), (engine_live_brain, engine_live_brain._live_command)):
            with self.subTest(module=module.__name__):
                source = inspect.getsource(function)
                prepare = source.index("brain_entry.prepare")
                present = source.index("brain_echo.present", prepare)
                self.assertLess(prepare, present)


if __name__ == "__main__":
    unittest.main()
