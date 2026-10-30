from __future__ import annotations

import inspect
import unittest

from modules.brain_contracts import ActiveContext, ContextReference
from modules.brain_reference import resolve_references


OWNER = "hamdi"
RID = "req-1"


def ref(ident: str, kind: str, *, source: str = "test", **provenance) -> ContextReference:
    return ContextReference(
        id=ident,
        kind=kind,
        source=source,
        owner=OWNER,
        provenance=provenance,
    )


def context(*, owner: str = OWNER, request_id: str = RID, **groups) -> ActiveContext:
    return ActiveContext(owner=owner, request_id=request_id, **groups)


class ReferenceResolverContractTests(unittest.TestCase):
    def call(self, text: str, candidates=(), active_context=None, owner=OWNER, request_id=RID):
        return resolve_references(
            owner=owner,
            request_id=request_id,
            text=text,
            active_context=active_context or context(),
            candidates=tuple(candidates),
        )

    def test_owner_and_request_fence_fail_closed(self):
        with self.assertRaises(ValueError):
            self.call("onu", owner="")
        with self.assertRaises(ValueError):
            self.call("onu", request_id="")
        with self.assertRaises(ValueError):
            self.call("onu", active_context=context(owner="other"))
        with self.assertRaises(ValueError):
            self.call("onu", active_context=context(request_id="other"))
        foreign = ContextReference(id="x", kind="note", source="test", owner="other")
        with self.assertRaises(ValueError):
            self.call("onu", [foreign])

    def test_blank_text_is_safe_and_empty_candidates_never_invent(self):
        candidate = ref("n1", "note", text="Bir not")
        self.assertEqual(self.call("", [candidate]), ())
        self.assertEqual(self.call("   ", [candidate]), ())
        self.assertEqual(self.call("son PDF'i özetle", []), ())

    def test_explicit_real_id_unique_and_unknown_id_does_not_invent(self):
        one = ref("task-42", "task", text="Raporu bitir")
        two = ref("task-99", "task", text="Sunumu bitir")
        self.assertEqual(self.call("task-42 durumunu göster", [one, two]), (one,))
        self.assertEqual(self.call("task-77 durumunu göster", [one, two]), ())

    def test_id_match_is_bounded_not_aggressive_substring(self):
        one = ref("12", "task", text="Rapor")
        self.assertEqual(self.call("312 numaralı şeyi aç", [one]), ())
        self.assertEqual(self.call("12 numaralı şeyi aç", [one]), (one,))

    def test_exact_title_unique_and_same_title_preserves_ambiguity(self):
        one = ref("n1", "note", title="Toplantı notu")
        two = ref("n2", "note", title="Başka not")
        self.assertEqual(self.call("Toplantı notu", [one, two]), (one,))
        self.assertEqual(self.call("Toplantı notu hakkında", [one, two]), (one,))
        duplicate_title = ref("n3", "note", title="Toplantı notu")
        self.assertEqual(self.call("Toplantı notu", [one, duplicate_title]), (one, duplicate_title))
        self.assertEqual(self.call("Toplantı notu hakkında", [one, duplicate_title]), (one, duplicate_title))

    def test_same_text_different_ids_are_not_deduped(self):
        one = ref("n1", "note", text="aynı metin")
        two = ref("n2", "note", text="aynı metin")
        self.assertEqual(self.call("aynı metin", [one, two]), (one, two))

    def test_file_full_path_filename_and_stem_resolution(self):
        one = ref(r"C:\Users\Hamdi\Documents\rapor.pdf", "file", source="nxapi.file_inventory",
                  path=r"C:\Users\Hamdi\Documents\rapor.pdf", name="rapor.pdf")
        other = ref(r"C:\Users\Hamdi\Documents\sunum.pdf", "file", source="nxapi.file_inventory",
                    path=r"C:\Users\Hamdi\Documents\sunum.pdf", name="sunum.pdf")
        self.assertEqual(self.call(r"C:\Users\Hamdi\Documents\rapor.pdf", [one, other]), (one,))
        self.assertEqual(self.call("rapor.pdf", [one, other]), (one,))
        self.assertEqual(self.call("rapor.pdf’i aç", [one, other]), (one,))
        self.assertEqual(self.call("rapor", [one, other]), (one,))

    def test_same_filename_or_stem_different_paths_preserves_ambiguity(self):
        one = ref(r"C:\A\rapor.pdf", "file", path=r"C:\A\rapor.pdf", name="rapor.pdf")
        two = ref(r"C:\B\rapor.pdf", "file", path=r"C:\B\rapor.pdf", name="rapor.pdf")
        self.assertEqual(self.call("rapor.pdf", [one, two]), (one, two))
        self.assertEqual(self.call("rapor.pdf’i aç", [one, two]), (one, two))
        self.assertEqual(self.call("rapor", [one, two]), (one, two))

    def test_file_resolution_is_not_permission(self):
        candidate = ref(r"C:\Users\Hamdi\Documents\a.pdf", "file", path=r"C:\Users\Hamdi\Documents\a.pdf",
                        name="a.pdf")
        result = self.call("a.pdf", [candidate])
        self.assertEqual(result, (candidate,))
        self.assertNotIn("allowed", candidate.provenance)
        self.assertNotIn("permission", candidate.provenance)
        self.assertNotIn("execute", candidate.provenance)

    def test_file_deictic_single_candidate_unique_multiple_ambiguous(self):
        one = ref(r"C:\A\a.pdf", "file", path=r"C:\A\a.pdf", name="a.pdf")
        two = ref(r"C:\B\b.pdf", "file", path=r"C:\B\b.pdf", name="b.pdf")
        for text in ("bu dosya", "son dosya", "yüklediğim dosya"):
            self.assertEqual(self.call(text, [one]), (one,))
            self.assertEqual(self.call(text, [one, two]), (one, two))
        self.assertEqual(self.call("son dosya", []), ())

    def test_last_note_single_candidate_unique_multiple_ambiguous(self):
        one = ref("n1", "note", title="Bir")
        two = ref("n2", "note", title="İki")
        self.assertEqual(self.call("son not", [one]), (one,))
        self.assertEqual(self.call("son not", [one, two]), (one, two))

    def test_last_answer_uses_only_assistant_conversation_candidates(self):
        user = ref("u1", "conversation_turn", source="history", role="user", text="sorum")
        assistant = ref("a1", "conversation_turn", source="history", role="assistant", text="cevap")
        self.assertEqual(self.call("son cevap", [user, assistant]), (assistant,))

    def test_generic_deictic_unique_and_ambiguous(self):
        one = ref("a1", "conversation_turn", source="history", role="assistant", text="cevap")
        two = ref("n1", "note", title="not")
        for text in ("onu", "bunu", "az önceki"):
            self.assertEqual(self.call(text, [one]), (one,))
            self.assertEqual(self.call(text, [one, two]), (one, two))

    def test_unrelated_sentence_does_not_consume_pending_state(self):
        pending = ref("pending_visual", "pending_state", source="session_state", field="pending_visual")
        active = context(pending_references=(pending,))
        self.assertEqual(self.call("yarın toplantım kaçta?", [pending], active), ())

    def test_pending_candidate_does_not_create_conversation_relation(self):
        pending = ref("pending_visual", "pending_state", source="session_state", field="pending_visual")
        result = self.call("yarın toplantım kaçta?", [pending], context(pending_references=(pending,)))
        self.assertIsInstance(result, tuple)
        self.assertFalse(hasattr(result, "conversation_relation"))

    def test_source_status_is_never_a_target(self):
        status = ref("history", "source_status", source="history", reason_code="SOURCE_UNAVAILABLE")
        self.assertEqual(self.call("onu", [status]), ())
        self.assertEqual(self.call("history", [status]), ())

    def test_duplicate_identity_preserves_first_input_object(self):
        current = ref("same", "artifact", source="session_state", label="Rapor")
        stale_memory = ref("same", "artifact", source="memory", label="Rapor")
        result = self.call("Rapor", [current, stale_memory])
        self.assertEqual(result, (current,))
        self.assertIs(result[0], current)

    def test_result_contains_only_original_input_objects_and_preserves_identity_fields(self):
        candidate = ref("n1", "note", source="profile.items", title="Notum", text="İçerik")
        result = self.call("Notum", [candidate])
        self.assertEqual(result, (candidate,))
        self.assertIs(result[0], candidate)
        self.assertEqual(result[0].id, candidate.id)
        self.assertEqual(result[0].source, candidate.source)
        self.assertEqual(result[0].owner, candidate.owner)
        self.assertIs(result[0].provenance, candidate.provenance)

    def test_malformed_candidate_fails_closed(self):
        with self.assertRaises(ValueError):
            self.call("onu", [object()])
        with self.assertRaises(ValueError):
            resolve_references(owner=OWNER, request_id=RID, text="onu", active_context=object(), candidates=())
        with self.assertRaises(ValueError):
            resolve_references(owner=OWNER, request_id=RID, text="onu", active_context=context(), candidates=[])

    def test_resolver_does_not_execute_callable_candidate_data(self):
        called = []
        with self.assertRaises(ValueError):
            ContextReference(id="x", kind="note", source="test", owner=OWNER,
                             provenance={"callback": lambda: called.append(True)})
        self.assertEqual(called, [])

    def test_deterministic_same_inputs_same_result(self):
        one = ref("n1", "note", title="Not")
        two = ref("n2", "note", title="Not")
        first = self.call("Not", [one, two])
        second = self.call("Not", [one, two])
        self.assertEqual(first, second)
        self.assertEqual(first, (one, two))

    def test_no_ttl_lifecycle_or_authority_surface(self):
        import modules.brain_reference as module
        source = inspect.getsource(module)
        forbidden = (
            "timedelta", "time.monotonic", "datetime.now", "ttl", "expiry", "expires",
            "nxapi.allowed", "permission_granted", "effect_allowed", "completed", "done =",
        )
        lowered = source.casefold()
        for token in forbidden:
            self.assertNotIn(token.casefold(), lowered)

    def test_no_source_reads_models_router_or_durable_state(self):
        import modules.brain_reference as module
        source = inspect.getsource(module).casefold()
        forbidden = (
            "modules.llm", "smart_router", "router.classify", "openai", "gemini", "groq", "ollama",
            "embedding", "profile(", "history.read", "goal_executor", "sessionstore", "nxapi.list_files",
            "_scan_files", "chat_translation", "workbench", "requests.", "urllib", "socket", "open(",
            ".write(", ".save(", "json.dump",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_public_surface_has_no_model_or_relation_parameter(self):
        params = inspect.signature(resolve_references).parameters
        self.assertEqual(tuple(params), ("owner", "request_id", "text", "active_context", "candidates"))
        self.assertNotIn("model", params)
        self.assertNotIn("conversation_relation", params)


if __name__ == "__main__":
    unittest.main()
