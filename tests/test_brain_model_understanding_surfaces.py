"""BRAIN-01: birincil model yüzeyleri — her serbest tur tek zarftan geçer, belirsizlik sahibi korunur.

Bu dosya iki şeyi birlikte doğrular: (1) `model_understanding` bayrağının gerçekten üretim
yüzeylerinde (Live, normal döngü, iç adım) açık olduğu, (2) owner-bound dosya belirsizliği
çözümünün yalnız konuşmadaki ad/klasör kanıtıyla mümkün olduğu. Model kararı artık kendisi
üretir; bu yüzden hiçbir test artık `propose` çıktısını taklit etmez, zarf transport düzeyinde
taklit edilir ve çitler gerçek üretim dikişinden geçer.
"""
from __future__ import annotations

import ast
import inspect
import json
import unittest
from unittest.mock import patch

from modules import brain_model_understanding as model
from modules.brain_contracts import (
    Confidence, ContextReference, ConversationRelation, RequestKind,
    TemporalNeed, UnderstandingResult,
)
from modules.brain_understanding import apply_model_understanding


OWNER = "hamdi"
RID = "model-understanding-test"


def make_result(**changes):
    values = dict(
        owner=OWNER,
        request_id=RID,
        request_kind=RequestKind.CHAT,
        capability_hint=None,
        arguments={"original_text": "Bugün biraz yoruldum."},
        references=(),
        conversation_relation=ConversationRelation.NEW_REQUEST,
        confidence=Confidence.MEDIUM,
        ambiguities=(),
        needs_input=False,
    )
    values.update(changes)
    return UnderstandingResult(**values)


def action(capability_id, arguments=None, slots=None, *, action_id="a1"):
    return {
        "action_id": action_id,
        "capability_id": capability_id,
        "arguments": arguments or {},
        "reference_slots": slots or [],
        "depends_on": [],
    }


def model_answer(**changes):
    values = {
        "schema_version": model.SCHEMA_VERSION,
        "operation": "chat",
        "conversation_relation": "NEW_REQUEST",
        "temporal_need": "UNSURE",
        "target_goal_ids": [],
        "goal": None,
        "actions": [],
        "clarification": {"required": False, "question": None, "reason_code": None},
        "confidence": "LOW",
    }
    values.update(changes)
    return json.dumps(values)


def file_read(operation, slots, **changes):
    changes.setdefault("confidence", "HIGH")
    return model_answer(operation="direct_action",
                        actions=[action("files.read", {"operation": operation}, slots)], **changes)


def eligible_provider_patches():
    return (
        patch("modules.llm.current_user", return_value=OWNER),
        patch("modules.llm.provider", return_value="groq"),
        patch("modules.llm.privacy.mode", return_value="normal"),
        patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}),
    )


def asked(raw, text, semantic, **kwargs):
    p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
    with p_owner, p_provider, p_privacy, p_selection, \
            patch("modules.smart_router.run", return_value=raw), \
            patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
        return model.propose(owner=OWNER, text=text, current=semantic,
                             arguments=semantic.arguments, **kwargs)


def asked_apply(raw, text, semantic):
    """Zarfı transport düzeyinde taklit eder; çitler ve benimseme gerçek dikişte çalışır."""
    p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
    with p_owner, p_provider, p_privacy, p_selection, \
            patch("modules.smart_router.run", return_value=raw), \
            patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
        return apply_model_understanding(semantic, text)


def file_ref(ident: str, path: str, name: str, owner: str = OWNER):
    return ContextReference(
        id=ident,
        kind="file",
        source="candidate",
        owner=owner,
        provenance={"path": path, "name": name},
    )


def ambiguous_files(first_path: str, second_path: str, text: str, name_first: str, name_second: str):
    first = file_ref("file-a", first_path, name_first)
    second = file_ref("file-b", second_path, name_second)
    semantic = make_result(
        request_kind=RequestKind.CLARIFY,
        capability_hint="files.read",
        arguments={"original_text": text},
        references=(first, second),
        confidence=Confidence.LOW,
        ambiguities=("multiple target references",),
        needs_input=True,
    )
    return first, second, semantic


class BrainAllTurnModelUnderstandingTests(unittest.TestCase):
    def test_model_cannot_downgrade_context_control_to_chat(self):
        semantic = make_result(
            request_kind=RequestKind.CONTEXT_CONTROL,
            conversation_relation=ConversationRelation.TOPIC_CHANGE,
            confidence=Confidence.HIGH,
        )
        raw = model_answer(operation="chat", conversation_relation="TOPIC_CHANGE",
                           temporal_need="STATIC", confidence="LOW")
        self.assertIsNone(asked(raw, "boşver, başka konuya geçelim", semantic,
                                protected_relation=True))

    def test_plain_chat_is_evaluated_without_a_keyword_or_capability_hint(self):
        semantic = make_result()
        with patch("modules.brain_model_understanding.propose", return_value=None) as propose:
            returned = apply_model_understanding(semantic, "Bugün biraz yoruldum.")
        self.assertIs(returned, semantic)
        propose.assert_called_once()
        self.assertEqual(propose.call_args.kwargs["text"], "Bugün biraz yoruldum.")

    def test_live_command_enables_the_same_model_understanding_path(self):
        from modules import engine_live_brain

        source = inspect.getsource(engine_live_brain._live_command)
        tree = ast.parse(source)
        enabled = [
            keyword.value.value
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "prepare"
            for keyword in call.keywords
            if keyword.arg == "model_understanding"
            and isinstance(keyword.value, ast.Constant)
        ]
        self.assertIn(True, enabled)

    def test_normal_command_loop_evaluates_every_free_form_turn(self):
        from modules import engine_loop

        source = inspect.getsource(engine_loop.main)
        tree = ast.parse(source)
        enabled = [
            keyword.value.value
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "prepare"
            for keyword in call.keywords
            if keyword.arg == "model_understanding"
            and isinstance(keyword.value, ast.Constant)
        ]
        self.assertIn(True, enabled)

    def test_nested_step_enables_model_understanding_for_its_own_utterance(self):
        from modules import brain_entry

        source = inspect.getsource(brain_entry.run_step)
        tree = ast.parse(source)
        enabled = [
            keyword.value.value
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "prepare"
            for keyword in call.keywords
            if keyword.arg == "model_understanding"
            and isinstance(keyword.value, ast.Constant)
        ]
        self.assertIn(True, enabled)

    def test_ambiguous_file_target_can_be_resolved_only_to_an_existing_candidate(self):
        text = "İndirilenlerdeki 2025 dosyasını özetle"
        first, second, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Butce\2025.xlsx",
            r"C:\Users\hamdi\Downloads\Fatura\2025.xlsx", text, "2025.xlsx", "2025.xlsx")
        raw = file_read("summarize", ["file_1"])
        resolved = asked(raw, text, semantic, file_operation_hint="summarize")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.actions[0].capability_id, "files.read")
        self.assertEqual(resolved.references, (second,))
        self.assertEqual(dict(resolved.actions[0].arguments), {
            "original_text": text, "operation": "summarize",
            "path": second.provenance["path"]})
        # The validated model chose HIGH; grounding the offered file slot
        # must preserve its confidence rather than letting old heuristic
        # confidence overwrite that decision. The path remains Core-bound.
        self.assertIs(resolved.confidence, Confidence.HIGH)

        applied = asked_apply(raw, text, semantic)
        self.assertIs(applied.request_kind, RequestKind.CAPABILITY)
        self.assertFalse(applied.needs_input)
        self.assertEqual(applied.ambiguities, ())
        self.assertEqual(applied.references, (second,))
        self.assertEqual(applied.arguments["path"], second.provenance["path"])
        self.assertIn("MODEL_REFERENCE_RESOLVED", applied.reason_codes)

    def test_indistinguishable_candidates_remain_a_user_clarification(self):
        text = "rapor.pdf'i aç"
        _, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Rapor\rapor.pdf",
            r"D:\Users\hamdi\Documents\Rapor\rapor.pdf", text, "rapor.pdf", "rapor.pdf")
        self.assertIsNone(asked(file_read("summarize", ["file_0"]), text, semantic,
                                file_operation_hint="summarize"))

    def test_grounded_file_model_operation_is_not_vetoed_by_legacy_keyword_hint(self):
        # The free-language operation belongs to the model. A deterministic
        # "summarize" hint must never become a competing semantic veto; Core
        # still rejects invented paths, unsupported operations and bad slots.
        text = "rapor dosyasını özetle"
        first, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Rapor\rapor.pdf",
            r"C:\Users\hamdi\Downloads\Rapor\son.pdf", text, "rapor.pdf", "son.pdf")
        resolved = asked(file_read("analyze", ["file_0"]), text, semantic,
                         file_operation_hint="summarize")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.references, (first,))
        self.assertEqual(resolved.actions[0].capability_id, "files.read")
        self.assertEqual(resolved.actions[0].arguments["operation"], "analyze")
        self.assertEqual(resolved.actions[0].arguments["path"], first.provenance["path"])

    def test_model_resolves_a_file_open_to_an_offered_exact_slot(self):
        text = "rapor.pdf'i aç"
        first, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Rapor\rapor.pdf",
            r"C:\Users\hamdi\Downloads\Rapor\son.pdf", text, "rapor.pdf", "son.pdf")
        decision = asked(file_read("open", ["file_0"]), text, semantic,
                         file_operation_hint="open")
        self.assertIsNotNone(decision)
        self.assertEqual(decision.references, (first,))
        self.assertEqual(decision.actions[0].arguments["operation"], "open")
        self.assertEqual(decision.actions[0].arguments["path"], first.provenance["path"])

    def test_model_chat_proposal_cannot_clear_ambiguous_file_target(self):
        text = "rapor.pdf'i aç"
        _, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Rapor\rapor.pdf",
            r"D:\Users\hamdi\Documents\Rapor\rapor.pdf", text, "rapor.pdf", "rapor.pdf")
        returned = asked_apply(model_answer(operation="chat", confidence="MEDIUM"), text, semantic)
        self.assertIs(returned, semantic)
        self.assertTrue(returned.needs_input)
        self.assertEqual(returned.request_kind, RequestKind.CLARIFY)

    def test_unresolved_ambiguity_stays_clarify_when_model_cannot_choose(self):
        text = "rapor.pdf'i aç"
        _, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Rapor\rapor.pdf",
            r"D:\Users\hamdi\Documents\Rapor\rapor.pdf", text, "rapor.pdf", "rapor.pdf")
        with patch("modules.brain_model_understanding.propose", return_value=None) as propose:
            returned = apply_model_understanding(semantic, text)
        propose.assert_called_once()
        self.assertIs(returned, semantic)
        self.assertTrue(returned.needs_input)
        self.assertEqual(returned.request_kind, RequestKind.CLARIFY)

    def test_non_file_reference_ambiguity_cannot_be_downgraded_to_chat(self):
        note_a = ContextReference(id="note-a", kind="note", source="candidate", owner=OWNER,
                                  provenance={"title": "Toplantı notu"})
        note_b = ContextReference(id="note-b", kind="note", source="candidate", owner=OWNER,
                                  provenance={"title": "Proje notu"})
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            arguments={"original_text": "onu göster"},
            references=(note_a, note_b),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        self.assertIsNone(asked(model_answer(operation="chat", confidence="LOW"),
                                "onu göster", semantic))

    def test_apply_model_understanding_preserves_non_file_target_clarification(self):
        note_a = ContextReference(id="note-a", kind="note", source="candidate", owner=OWNER,
                                  provenance={"title": "Toplantı notu"})
        note_b = ContextReference(id="note-b", kind="note", source="candidate", owner=OWNER,
                                  provenance={"title": "Proje notu"})
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            arguments={"original_text": "onu göster"},
            references=(note_a, note_b),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        returned = asked_apply(model_answer(operation="chat", confidence="MEDIUM"),
                               "onu göster", semantic)
        self.assertIs(returned, semantic)
        self.assertTrue(returned.needs_input)
        self.assertEqual(returned.ambiguities, ("multiple target references",))

    def test_ambiguous_file_resolution_rejects_candidate_from_unmentioned_folder(self):
        text = "İndirilenlerdeki 2025 dosyasını özetle"
        _, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Butce\2025.xlsx",
            r"C:\Users\hamdi\Downloads\Fatura\2025.xlsx", text, "2025.xlsx", "2025.xlsx")
        self.assertIsNone(asked(file_read("summarize", ["file_0"]), text, semantic,
                                file_operation_hint="summarize"))

    def test_duplicate_file_name_without_folder_context_stays_ambiguous(self):
        text = "2025 dosyasını özetle"
        _, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\Butce\2025.xlsx",
            r"C:\Users\hamdi\Downloads\Fatura\2025.xlsx", text, "2025.xlsx", "2025.xlsx")
        self.assertIsNone(asked(file_read("summarize", ["file_1"]), text, semantic,
                                file_operation_hint="summarize"))

    def test_unique_file_name_is_enough_when_candidates_share_a_folder(self):
        text = "2025 dosyasını özetle"
        first, _, semantic = ambiguous_files(
            r"C:\Users\hamdi\Documents\2025.xlsx",
            r"C:\Users\hamdi\Documents\2026.xlsx", text, "2025.xlsx", "2026.xlsx")
        resolved = asked(file_read("summarize", ["file_0"]), text, semantic,
                         file_operation_hint="summarize")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.references, (first,))
        self.assertEqual(dict(resolved.actions[0].arguments)["path"], first.provenance["path"])

    def test_file_candidate_grounding_is_independent_of_model_slot(self):
        first = file_ref("file-a", r"C:\Users\hamdi\Documents\Butce\2025.xlsx", "2025.xlsx")
        second = file_ref("file-b", r"C:\Users\hamdi\Downloads\Fatura\2025.xlsx", "2025.xlsx")
        self.assertFalse(model._selected_file_candidate_is_grounded(
            "İndirilenlerdeki 2025 dosyasını özetle", first, [first, second]
        ))
        self.assertTrue(model._selected_file_candidate_is_grounded(
            "İndirilenlerdeki 2025 dosyasını özetle", second, [first, second]
        ))
        self.assertFalse(model._selected_file_candidate_is_grounded(
            "2025 dosyasını özetle", second, [first, second]
        ))

        unique_first = file_ref("file-c", r"C:\Users\hamdi\Documents\2025.xlsx", "2025.xlsx")
        unique_second = file_ref("file-d", r"C:\Users\hamdi\Documents\2026.xlsx", "2026.xlsx")
        self.assertTrue(model._selected_file_candidate_is_grounded(
            "2025 dosyasını özetle", unique_first, [unique_first, unique_second]
        ))


if __name__ == "__main__":
    unittest.main()
