from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from modules.brain_contracts import ActiveContext, ContextReference
from modules.brain_candidates import build_candidates


class CandidateBuilderTests(unittest.TestCase):
    def _context(self, *, owner="hamdi", request_id="req-1", **kwargs):
        return ActiveContext(owner=owner, request_id=request_id, **kwargs)

    def _profile(self, owner="hamdi", **data):
        return SimpleNamespace(slug=owner, data=data, save=Mock())

    def _build(self, **kwargs):
        defaults = {
            "owner": "hamdi",
            "request_id": "req-1",
            "text": "dosya görev not takvim",
            "active_context": self._context(),
            "profile": self._profile(tasks=[], items=[], events=[], goals=[], facts=[], rules=[]),
            "file_reader": lambda limit=80: [],
        }
        defaults.update(kwargs)
        return build_candidates(**defaults)

    def test_blank_owner_rejected(self):
        with self.assertRaises(ValueError): self._build(owner="")

    def test_blank_request_id_rejected(self):
        with self.assertRaises(ValueError): self._build(request_id="")

    def test_blank_text_rejected(self):
        with self.assertRaises(ValueError): self._build(text="   ")

    def test_active_context_owner_mismatch_fails_closed(self):
        with self.assertRaises(ValueError): self._build(active_context=self._context(owner="hasan"))

    def test_active_context_request_id_mismatch_fails_closed(self):
        with self.assertRaises(ValueError): self._build(active_context=self._context(request_id="other"))

    def test_empty_sources_return_empty_tuple(self):
        self.assertEqual(self._build(), ())

    def test_empty_sources_do_not_invent_candidate(self):
        self.assertFalse(self._build())

    def test_cross_owner_profile_fails_closed(self):
        with self.assertRaises(ValueError): self._build(profile=self._profile(owner="hasan", tasks=[]))

    def test_task_stable_id_is_preserved(self):
        profile = self._profile(tasks=[{"id": 17, "text": "Raporu bitir", "done": False}], items=[], events=[])
        ref = self._build(profile=profile)[0]
        self.assertEqual((ref.id, ref.kind, ref.source, ref.owner), ("17", "task", "profile.tasks", "hamdi"))

    def test_note_stable_id_is_preserved(self):
        profile = self._profile(tasks=[], items=[{"id": 9, "title": "Fikir", "text": "Yeni akış"}], events=[])
        ref = self._build(profile=profile)[0]
        self.assertEqual((ref.id, ref.kind, ref.source), ("9", "note", "profile.items"))

    def test_event_stable_id_is_preserved(self):
        profile = self._profile(tasks=[], items=[], events=[{"id": 4, "title": "Toplantı", "when": "2026-10-31T10:00"}])
        ref = self._build(profile=profile)[0]
        self.assertEqual((ref.id, ref.kind, ref.source), ("4", "event", "profile.events"))

    def test_goal_without_stable_id_is_not_targetable(self):
        profile = self._profile(tasks=[], items=[], events=[], goals=["Jarvis'i geliştir"])
        self.assertEqual(self._build(profile=profile), ())

    def test_fact_without_stable_id_is_not_targetable(self):
        profile = self._profile(tasks=[], items=[], events=[], facts=["Kısa cevap tercih ediyor"])
        self.assertEqual(self._build(profile=profile), ())

    def test_rule_without_stable_id_is_not_targetable(self):
        profile = self._profile(tasks=[], items=[], events=[], rules=["Test geçmeden tamam deme"])
        self.assertEqual(self._build(profile=profile), ())

    def test_file_candidate_keeps_real_path_identity_and_provenance(self):
        row = {"path": "C:/Users/Hamdi/Documents/a.pdf", "name": "a.pdf", "mtime": 123.0, "mine": False, "where": "Belgeler"}
        ref = self._build(file_reader=lambda limit=80: [row])[0]
        self.assertEqual(ref.id, row["path"])
        self.assertEqual(ref.kind, "file")
        self.assertEqual(ref.provenance["path"], row["path"])

    def test_file_candidate_has_no_permission_or_allowed_authority(self):
        row = {"path": "C:/Users/Hamdi/Documents/a.pdf", "name": "a.pdf"}
        payload = self._build(file_reader=lambda limit=80: [row])[0].to_dict()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('"allowed"', text)
        self.assertNotIn('"permission"', text)
        self.assertNotIn('"authorized"', text)

    def test_global_file_inventory_does_not_claim_user_ownership(self):
        row = {"path": "C:/Users/Hamdi/Desktop/a.txt", "name": "a.txt", "mine": False}
        ref = self._build(file_reader=lambda limit=80: [row])[0]
        self.assertEqual(ref.owner, "hamdi")
        self.assertEqual(ref.provenance["inventory_scope"], "global_pc")
        self.assertNotIn("owned_by", ref.provenance)

    def test_active_live_candidate_precedes_memory_duplicate(self):
        live = ContextReference(id="42", kind="task", source="active_context", owner="hamdi", provenance={"state": "live"})
        memory = ContextReference(id="42", kind="task", source="memory", owner="hamdi", provenance={"state": "old"})
        context = self._context(active_task_references=(live,), memory_references=(memory,))
        refs = self._build(active_context=context)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].source, "active_context")

    def test_identity_duplicate_is_deterministically_deduped(self):
        a = ContextReference(id="x", kind="artifact", source="live", owner="hamdi")
        b = ContextReference(id="x", kind="artifact", source="memory", owner="hamdi")
        context = self._context(active_artifacts=(a,), memory_references=(b,))
        first = self._build(active_context=context)
        second = self._build(active_context=context)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)

    def test_same_name_different_entities_are_not_merged(self):
        profile = self._profile(tasks=[{"id": 1, "text": "Rapor"}, {"id": 2, "text": "Rapor"}], items=[], events=[])
        refs = self._build(profile=profile)
        self.assertEqual([r.id for r in refs], ["1", "2"])

    def test_reset_filtered_history_only_uses_active_context_reference(self):
        recent = ContextReference(id="new", kind="conversation_turn", source="history", owner="hamdi", provenance={"text": "yeni"})
        context = self._context(recent_references=(recent,))
        refs = self._build(active_context=context)
        self.assertEqual([r.id for r in refs], ["new"])

    def test_provider_exception_produces_no_fake_candidate(self):
        def broken(limit=80): raise OSError("offline")
        self.assertEqual(self._build(file_reader=broken), ())

    def test_provider_exception_never_falls_back_to_other_owner(self):
        def broken(limit=80): raise OSError("offline")
        profile = self._profile(owner="hamdi", tasks=[], items=[], events=[])
        refs = self._build(profile=profile, file_reader=broken)
        self.assertTrue(all(r.owner == "hamdi" for r in refs))

    def test_no_llm_or_model_dependency_is_called(self):
        model = Mock(side_effect=AssertionError("model çağrılmamalı"))
        self._build(model=model)
        model.assert_not_called()

    def test_builder_does_not_select_target(self):
        profile = self._profile(tasks=[{"id": 1, "text": "Rapor"}, {"id": 2, "text": "Rapor"}], items=[], events=[])
        self.assertEqual(len(self._build(profile=profile, text="rapor")), 2)

    def test_builder_does_not_resolve_ambiguity(self):
        profile = self._profile(tasks=[], items=[{"id": 1, "title": "Plan"}, {"id": 2, "title": "Plan"}], events=[])
        self.assertEqual(len(self._build(profile=profile, text="plan notu")), 2)

    def test_candidate_payload_has_no_permission_effect_fields(self):
        profile = self._profile(tasks=[{"id": 1, "text": "Rapor"}], items=[], events=[])
        text = json.dumps([x.to_dict() for x in self._build(profile=profile)], ensure_ascii=False)
        for forbidden in ("permission", "effect_allowed", "approved", "execute"):
            self.assertNotIn(forbidden, text)

    def test_callable_objects_never_enter_candidate(self):
        profile = self._profile(tasks=[{"id": 1, "text": "Rapor", "callback": lambda: None}], items=[], events=[])
        payload = self._build(profile=profile)[0].to_dict()
        self.assertNotIn("callback", json.dumps(payload, ensure_ascii=False))

    def test_source_state_is_not_mutated(self):
        data = {"tasks": [{"id": 1, "text": "Rapor"}], "items": [], "events": []}
        before = copy.deepcopy(data)
        profile = self._profile(**data)
        self._build(profile=profile)
        self.assertEqual(profile.data, before)

    def test_source_write_is_never_called(self):
        profile = self._profile(tasks=[{"id": 1, "text": "Rapor"}], items=[], events=[])
        self._build(profile=profile)
        profile.save.assert_not_called()

    def test_no_durable_brain_state_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = list(root.iterdir())
            self._build()
            self.assertEqual(list(root.iterdir()), before)

    def test_same_input_produces_deterministic_output(self):
        profile = self._profile(tasks=[{"id": 2, "text": "B"}, {"id": 1, "text": "A"}], items=[], events=[])
        first = self._build(profile=profile)
        second = self._build(profile=profile)
        self.assertEqual(first, second)

    def test_every_candidate_owner_matches_request_owner(self):
        profile = self._profile(tasks=[{"id": 1, "text": "A"}], items=[{"id": 2, "text": "B"}], events=[])
        self.assertTrue(all(r.owner == "hamdi" for r in self._build(profile=profile)))

    def test_candidate_provenance_names_real_source_collection(self):
        profile = self._profile(tasks=[{"id": 1, "text": "A"}], items=[], events=[])
        ref = self._build(profile=profile)[0]
        self.assertEqual(ref.provenance["collection"], "tasks")

    def test_result_is_immutable_canonical_context_reference_tuple(self):
        profile = self._profile(tasks=[{"id": 1, "text": "A"}], items=[], events=[])
        refs = self._build(profile=profile)
        self.assertIsInstance(refs, tuple)
        self.assertTrue(all(isinstance(r, ContextReference) for r in refs))
        with self.assertRaises(Exception):
            refs[0].id = "changed"

    def test_profile_rows_without_id_are_skipped_not_indexed(self):
        profile = self._profile(tasks=[{"text": "A"}], items=[{"text": "B"}], events=[{"title": "C"}])
        self.assertEqual(self._build(profile=profile), ())

    def test_active_context_is_not_mutated(self):
        ref = ContextReference(id="x", kind="artifact", source="session_state", owner="hamdi", provenance={"path": "a"})
        context = self._context(active_artifacts=(ref,))
        before = context.to_dict()
        self._build(active_context=context)
        self.assertEqual(context.to_dict(), before)

    def test_bounded_profile_provider(self):
        profile = self._profile(tasks=[{"id": i, "text": str(i)} for i in range(100)], items=[], events=[])
        refs = self._build(profile=profile, provider_limit=20)
        self.assertEqual(len(refs), 20)

    def test_bounded_file_provider(self):
        rows = [{"path": f"C:/tmp/{i}.txt", "name": f"{i}.txt"} for i in range(100)]
        refs = self._build(file_reader=lambda limit=80: rows, provider_limit=20)
        self.assertEqual(len(refs), 20)


if __name__ == "__main__":
    unittest.main()
