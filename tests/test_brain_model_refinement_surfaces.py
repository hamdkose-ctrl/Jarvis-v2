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
from modules.brain_understanding import apply_model_refinement


OWNER = "hamdi"
RID = "model-refinement-test"


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


def model_answer(**changes):
    values = {
        "request_kind": "CLARIFY",
        "conversation_relation": "NEW_REQUEST",
        "temporal_need": "UNSURE",
        "capability_hint": None,
        "confidence": "LOW",
        "file_operation": None,
        "file_slots": [],
    }
    values.update(changes)
    return json.dumps(values)


def eligible_provider_patches():
    return (
        patch("modules.llm.current_user", return_value=OWNER),
        patch("modules.llm.provider", return_value="groq"),
        patch("modules.llm.privacy.mode", return_value="normal"),
        patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}),
    )


def file_ref(ident: str, path: str, name: str, owner: str = OWNER):
    return ContextReference(
        id=ident,
        kind="file",
        source="candidate",
        owner=owner,
        provenance={"path": path, "name": name},
    )


class BrainAllTurnModelRefinementTests(unittest.TestCase):
    def test_model_cannot_downgrade_context_control_to_chat(self):
        semantic = make_result(
            request_kind=RequestKind.CONTEXT_CONTROL,
            conversation_relation=ConversationRelation.TOPIC_CHANGE,
            confidence=Confidence.HIGH,
        )
        p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
        raw = model_answer(
            request_kind="CHAT",
            conversation_relation="TOPIC_CHANGE",
            temporal_need="STATIC",
            confidence="LOW",
        )
        with p_owner, p_provider, p_privacy, p_selection, \
                patch("modules.smart_router.run", return_value=raw):
            refined = model.refine(
                owner=OWNER,
                text="boşver, başka konuya geçelim",
                current=semantic,
                arguments=semantic.arguments,
                protected_relation=True,
            )
        self.assertIsNone(refined)

    def test_plain_chat_is_evaluated_without_a_keyword_or_capability_hint(self):
        semantic = make_result()
        with patch("modules.brain_model_understanding.refine", return_value=None) as refine:
            returned = apply_model_refinement(semantic, "Bugün biraz yoruldum.")
        self.assertIs(returned, semantic)
        refine.assert_called_once()
        self.assertEqual(refine.call_args.kwargs["text"], "Bugün biraz yoruldum.")

    def test_live_command_enables_the_same_model_refinement_path(self):
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
            if keyword.arg == "model_refinement"
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
            if keyword.arg == "model_refinement"
            and isinstance(keyword.value, ast.Constant)
        ]
        self.assertIn(True, enabled)

    def test_nested_step_enables_model_refinement_for_its_own_utterance(self):
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
            if keyword.arg == "model_refinement"
            and isinstance(keyword.value, ast.Constant)
        ]
        self.assertIn(True, enabled)

    def test_ambiguous_file_target_can_be_resolved_only_to_an_existing_candidate(self):
        first = file_ref("file-a", r"C:\Users\hamdi\Documents\Butce\2025.xlsx", "2025.xlsx")
        second = file_ref("file-b", r"C:\Users\hamdi\Downloads\Fatura\2025.xlsx", "2025.xlsx")
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            capability_hint="files.read",
            arguments={"original_text": "İndirilenlerdeki 2025 dosyasını özetle"},
            references=(first, second),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
        raw = model_answer(
            request_kind="CAPABILITY",
            capability_hint="files.read",
            confidence="HIGH",
            file_operation="summarize",
            file_slots=["file_1"],
        )
        with p_owner, p_provider, p_privacy, p_selection, \
                patch("modules.smart_router.run", return_value=raw), \
                patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
            refined = model.refine(
                owner=OWNER,
                text="İndirilenlerdeki 2025 dosyasını özetle",
                current=semantic,
                arguments=semantic.arguments,
                file_operation_hint="summarize",
            )
        self.assertIsNotNone(refined)
        self.assertEqual(refined.capability_hint, "files.read")
        self.assertEqual(refined.references, (second,))
        self.assertEqual(refined.arguments["path"], second.provenance["path"])
        self.assertEqual(refined.arguments["operation"], "summarize")
        # Only this grounded, read-only reference-resolution case may move LOW to MEDIUM.
        self.assertIs(refined.confidence, Confidence.MEDIUM)

        with patch("modules.brain_model_understanding.refine", return_value=refined):
            applied = apply_model_refinement(semantic, "İndirilenlerdeki 2025 dosyasını özetle")
        self.assertIs(applied.request_kind, RequestKind.CAPABILITY)
        self.assertFalse(applied.needs_input)
        self.assertEqual(applied.ambiguities, ())
        self.assertEqual(applied.references, (second,))
        self.assertEqual(applied.arguments["path"], second.provenance["path"])

    def test_indistinguishable_candidates_remain_a_user_clarification(self):
        first = file_ref("file-a", r"C:\Users\hamdi\Documents\Rapor\rapor.pdf", "rapor.pdf")
        second = file_ref("file-b", r"D:\Users\hamdi\Documents\Rapor\rapor.pdf", "rapor.pdf")
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            capability_hint="files.read",
            arguments={"original_text": "rapor.pdf'i aç"},
            references=(first, second),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
        raw = model_answer(
            request_kind="CAPABILITY",
            capability_hint="files.read",
            confidence="HIGH",
            file_operation="summarize",
            file_slots=["file_0"],
        )
        with p_owner, p_provider, p_privacy, p_selection, \
                patch("modules.smart_router.run", return_value=raw), \
                patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
            refined = model.refine(
                owner=OWNER, text="rapor.pdf'i aç", current=semantic,
                arguments=semantic.arguments, file_operation_hint="summarize",
            )
        self.assertIsNone(refined)

    def test_ambiguity_resolution_cannot_change_the_requested_read_operation(self):
        first = file_ref("file-a", r"C:\Users\hamdi\Documents\Rapor\rapor.pdf", "rapor.pdf")
        second = file_ref("file-b", r"C:\Users\hamdi\Downloads\Rapor\son.pdf", "son.pdf")
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            capability_hint="files.read",
            arguments={"original_text": "rapor dosyasını özetle"},
            references=(first, second),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
        raw = model_answer(
            request_kind="CAPABILITY",
            capability_hint="files.read",
            confidence="HIGH",
            file_operation="analyze",
            file_slots=["file_0"],
        )
        with p_owner, p_provider, p_privacy, p_selection, \
                patch("modules.smart_router.run", return_value=raw):
            refined = model.refine(
                owner=OWNER, text="rapor dosyasını özetle", current=semantic,
                arguments=semantic.arguments, file_operation_hint="summarize",
            )
        self.assertIsNone(refined)

    def test_ambiguous_file_open_is_not_resolved_by_the_model(self):
        first = file_ref("file-a", r"C:\Users\hamdi\Documents\Rapor\rapor.pdf", "rapor.pdf")
        second = file_ref("file-b", r"C:\Users\hamdi\Downloads\Rapor\son.pdf", "son.pdf")
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            capability_hint="files.read",
            arguments={"original_text": "rapor.pdf'i aç"},
            references=(first, second),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
        raw = model_answer(
            request_kind="CAPABILITY",
            capability_hint="files.read",
            confidence="HIGH",
            file_operation="open",
            file_slots=["file_0"],
        )
        with p_owner, p_provider, p_privacy, p_selection, \
                patch("modules.smart_router.run", return_value=raw):
            refined = model.refine(
                owner=OWNER, text="rapor.pdf'i aç", current=semantic,
                arguments=semantic.arguments, file_operation_hint="open",
            )
        self.assertIsNone(refined)

    def test_model_chat_proposal_cannot_clear_ambiguous_file_target(self):
        first = file_ref("file-a", r"C:\Users\hamdi\Documents\Rapor\rapor.pdf", "rapor.pdf")
        second = file_ref("file-b", r"C:\Users\hamdi\Downloads\Rapor\rapor.pdf", "rapor.pdf")
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            capability_hint="files.read",
            arguments={"original_text": "rapor.pdf'i aç"},
            references=(first, second),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        with patch("modules.brain_model_understanding.refine", return_value=None) as refine:
            returned = apply_model_refinement(semantic, "rapor.pdf'i aç")
        refine.assert_called_once()
        self.assertIs(returned, semantic)
        self.assertTrue(returned.needs_input)
        self.assertEqual(returned.request_kind, RequestKind.CLARIFY)

    def test_unresolved_ambiguity_stays_clarify_when_model_cannot_choose(self):
        first = file_ref("file-a", r"C:\Users\hamdi\Documents\Rapor\rapor.pdf", "rapor.pdf")
        second = file_ref("file-b", r"C:\Users\hamdi\Downloads\Rapor\rapor.pdf", "rapor.pdf")
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            capability_hint="files.read",
            arguments={"original_text": "rapor.pdf'i aç"},
            references=(first, second),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        with patch("modules.brain_model_understanding.refine", return_value=None) as refine:
            returned = apply_model_refinement(semantic, "rapor.pdf'i aç")
        refine.assert_called_once()
        self.assertIs(returned, semantic)
        self.assertTrue(returned.needs_input)
        self.assertEqual(returned.request_kind, RequestKind.CLARIFY)


    def test_non_file_reference_ambiguity_cannot_be_downgraded_to_chat(self):
        note_a = ContextReference(
            id="note-a", kind="note", source="candidate", owner=OWNER,
            provenance={"title": "Toplantı notu"},
        )
        note_b = ContextReference(
            id="note-b", kind="note", source="candidate", owner=OWNER,
            provenance={"title": "Proje notu"},
        )
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            arguments={"original_text": "onu göster"},
            references=(note_a, note_b),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        p_owner, p_provider, p_privacy, p_selection = eligible_provider_patches()
        raw = model_answer(request_kind="CHAT", confidence="LOW")
        with p_owner, p_provider, p_privacy, p_selection, \\
                patch("modules.smart_router.run", return_value=raw):
            refined = model.refine(
                owner=OWNER, text="onu göster", current=semantic,
                arguments=semantic.arguments,
            )
        self.assertIsNone(refined)

    def test_apply_model_refinement_preserves_non_file_target_clarification(self):
        from modules.brain_model_understanding import SemanticRefinement

        note_a = ContextReference(
            id="note-a", kind="note", source="candidate", owner=OWNER,
            provenance={"title": "Toplantı notu"},
        )
        note_b = ContextReference(
            id="note-b", kind="note", source="candidate", owner=OWNER,
            provenance={"title": "Proje notu"},
        )
        semantic = make_result(
            request_kind=RequestKind.CLARIFY,
            arguments={"original_text": "onu göster"},
            references=(note_a, note_b),
            confidence=Confidence.LOW,
            ambiguities=("multiple target references",),
            needs_input=True,
        )
        chat_proposal = SemanticRefinement(
            request_kind=RequestKind.CHAT,
            conversation_relation=ConversationRelation.NEW_REQUEST,
            temporal_need=TemporalNeed.UNSURE,
            capability_hint=None,
            confidence=Confidence.LOW,
        )
        with patch("modules.brain_model_understanding.refine", return_value=chat_proposal):
            returned = apply_model_refinement(semantic, "onu göster")
        self.assertIs(returned, semantic)
        self.assertTrue(returned.needs_input)
        self.assertEqual(returned.ambiguities, ("multiple target references",))


if __name__ == "__main__":
    unittest.main()
