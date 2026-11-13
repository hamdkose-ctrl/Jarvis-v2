"""Notes search + summary canonical migration: Understanding -> Core -> notes domain owner.

RED phase contract:
- search/summary must be proposed by canonical Understanding and validated by Core;
- ``main_planner._note_lookup`` (legacy raw-text search) must not be required;
- summary must never fall back to the generic chat arm;
- an unresolved/ambiguous target, empty query and malformed Core payload must fail closed;
- other domains (web/file/mail/page) keep their own target ownership.
"""
import ast
import copy
from dataclasses import replace
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_core_map, brain_entry, brain_reference, brain_understanding, engine_runtime, requests_state
from modules.brain_contracts import ActiveContext, ContextReference, RequestKind

SEARCH_QUERY_MISSING = "note search query missing"


def note_ref(ident, text="market listesi", **provenance):
    return ContextReference(id=str(ident), kind="note", source="profile.items", owner=fx.OWNER,
                            provenance={"collection": "items", "text": text, **provenance})


def understand(text, refs=(), *, active=None):
    context = active or fx.context()
    return brain_understanding.understand(
        owner=fx.OWNER, request_id=fx.RID, text=text, active_context=context,
        candidates=tuple(refs), references=tuple(refs),
    )


def resolve(text, refs=(), *, active=None):
    context = active or fx.context()
    return brain_reference.resolve_references(
        owner=fx.OWNER, request_id=fx.RID, text=text, active_context=context, candidates=tuple(refs),
    )


class UnderstandingSearchTests(unittest.TestCase):
    def test_required_search_phrases_propose_typed_query(self):
        cases = {
            "notlarımda proje alfa ara": "proje alfa",
            "proje alfa geçen notu bul": "proje alfa",
            "notlarda toplantı geçenleri göster": "toplantı",
            "hangi notumda bütçe yazıyor": "bütçe",
        }
        for text, query in cases.items():
            with self.subTest(text=text):
                result = understand(text)
                self.assertEqual(result.capability_hint, "notes.read", text)
                self.assertEqual(result.arguments.get("notes"), {"which": "search", "query": query}, text)

    def test_date_window_is_a_typed_structured_field(self):
        result = understand("bugünkü notlarım")
        self.assertEqual(result.arguments.get("notes"), {"which": "search", "window": "today"})
        self.assertIn("notes", result.arguments)

    def test_empty_query_is_a_fail_closed_clarification(self):
        result = understand("notlarımda ara")
        self.assertTrue(result.needs_input)
        self.assertIn(SEARCH_QUERY_MISSING, result.ambiguities)
        self.assertNotIn("notes", result.arguments)

    def test_search_does_not_steal_other_domains(self):
        for text in ("internette yapay zeka ara", "dosyada bütçe ara", "mailde bütçe ara",
                     "bu dosyayı özetle", "maili özetle", "web sayfasını özetle", "noter göster"):
            with self.subTest(text=text):
                result = understand(text)
                self.assertNotEqual(result.capability_hint, "notes.read", text)
                self.assertNotIn("notes", result.arguments, text)

    def test_multi_intent_sentence_keeps_search_out_of_the_plan(self):
        for text in ("notları göster ve hava durumu nasıl", "notlarımı göster, haberleri oku",
                     "notlarımı göster ve sil"):
            with self.subTest(text=text):
                result = understand(text)
                self.assertNotEqual(result.arguments.get("notes", {}).get("which"), "search", text)


class UnderstandingSummaryTests(unittest.TestCase):
    def test_all_notes_summary_is_one_canonical_operation(self):
        for text in ("notlarımı özetle", "tüm notlarımı özetle"):
            with self.subTest(text=text):
                result = understand(text)
                self.assertEqual(result.capability_hint, "notes.read", text)
                self.assertEqual(result.arguments.get("notes"), {"which": "summary"}, text)

    def test_ordinal_summary_resolves_through_candidate_reference(self):
        refs = (note_ref("n1", "süt al", list_position=1, list_count=2),
                note_ref("n2", "diş randevusu", list_position=2, list_count=2))
        resolved = resolve("ikinci notumu özetle", refs)
        self.assertEqual([ref.id for ref in resolved], ["n2"])
        result = understand("ikinci notumu özetle", resolved)
        self.assertEqual(result.arguments.get("notes"), {"which": "summary", "id": "n2"})

    def test_named_summary_uses_the_existing_reference_resolver(self):
        refs = (note_ref("n1", "proje alfa toplantı"), note_ref("n2", "proje beta"))
        resolved = resolve("proje alfa başlıklı notu özetle", refs)
        self.assertEqual([ref.id for ref in resolved], ["n1"])
        result = understand("proje alfa başlıklı notu özetle", resolved)
        self.assertEqual(result.arguments.get("notes"), {"which": "summary", "id": "n1"})

    def test_ambiguous_named_summary_never_picks_one(self):
        refs = (note_ref("n1", "market süt"), note_ref("n2", "market ekmek"))
        resolved = resolve("market notunu özetle", refs)
        self.assertEqual(len(resolved), 2)
        result = understand("market notunu özetle", resolved)
        self.assertTrue(result.needs_input)
        self.assertNotIn("notes", result.arguments)

    def test_deictic_summary_without_active_note_context_fails_closed(self):
        for text in ("bu notu özetle", "şu notu özetle", "o notu özetle"):
            with self.subTest(text=text):
                result = understand(text)
                self.assertTrue(result.needs_input, text)
                self.assertIn("note target unresolved", result.ambiguities, text)
                self.assertNotIn("notes", result.arguments, text)

    def test_deictic_summary_uses_only_an_existing_active_note_reference(self):
        ref = note_ref("n9", "aktif not")
        active = ActiveContext(owner=fx.OWNER, request_id=fx.RID, recent_references=(ref,))
        resolved = resolve("bu notu özetle", (ref,), active=active)
        self.assertEqual([row.id for row in resolved], ["n9"])
        result = understand("bu notu özetle", resolved, active=active)
        self.assertEqual(result.arguments.get("notes"), {"which": "summary", "id": "n9"})

    def test_summary_does_not_steal_other_domains(self):
        for text in ("bu dosyayı özetle", "maili özetle", "web sayfasını özetle", "bu sayfayı özetle"):
            with self.subTest(text=text):
                result = understand(text)
                self.assertNotEqual(result.arguments.get("notes", {}).get("which"), "summary", text)


class CoreValidationTests(unittest.TestCase):
    def test_search_and_summary_payloads_are_core_validated(self):
        self.assertEqual(
            brain_core_map.core_plan("notes.read", {"notes": {"which": "search", "query": " proje alfa "}}),
            ("notes_read", {"which": "search", "query": "proje alfa"}),
        )
        self.assertEqual(
            brain_core_map.core_plan("notes.read", {"notes": {"which": "search", "window": "last_week"}}),
            ("notes_read", {"which": "search", "window": "last_week"}),
        )
        self.assertEqual(
            brain_core_map.core_plan("notes.read", {"notes": {"which": "summary"}}),
            ("notes_read", {"which": "summary"}),
        )
        self.assertEqual(
            brain_core_map.core_plan("notes.read", {"notes": {"which": "summary", "id": " n1 "}}),
            ("notes_read", {"which": "summary", "id": "n1"}),
        )

    def test_malformed_search_summary_payloads_fail_closed(self):
        bad = (
            {"notes": {"which": "search"}},
            {"notes": {"which": "search", "query": ""}},
            {"notes": {"which": "search", "query": 7}},
            {"notes": {"which": "search", "query": "a\x00b"}},
            {"notes": {"which": "search", "query": "bir iki üç dört"}},
            {"notes": {"which": "search", "query": "x", "window": "forever"}},
            {"notes": {"which": "search", "query": "x", "id": "n1"}},
            {"notes": {"which": "summary", "id": 7}},
            {"notes": {"which": "summary", "id": "x" * 65}},
            {"notes": {"which": "summary", "query": "x"}},
            {"notes": {"which": "all", "id": "n1"}},
            {"notes": {"which": "delete"}},
            {"notes": {"which": "one", "id": 7}},
            {"notes": {"which": "all", "extra": 1}},
            {"notes": "all"},
        )
        for payload in bad:
            with self.subTest(payload=payload):
                self.assertIsNone(brain_core_map.core_plan("notes.read", payload), payload)

    def test_partial_hint_entry_is_retired_only_for_notes(self):
        self.assertNotIn("notes.read", brain_core_map.PARTIAL_CORE_HINTS)
        self.assertNotIn("notes.read", brain_core_map.LEGACY_OWNED_HINTS)
        self.assertEqual(brain_core_map.hint_owner("notes.read"), "core:notes_read")
        # Other capabilities keep their own partial ownership untouched.
        self.assertIn("research.search", brain_core_map.PARTIAL_CORE_HINTS)


class _BrainCase(unittest.TestCase):
    now_texts = (
        "proje alfa toplantı notları",
        "proje beta fikirleri",
        "bütçe raporu hazırla",
        "market: süt ekmek",
        "Ahmet ile toplantı",
    )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        from test_mail_calendar_fixes import _release_logs
        self.addCleanup(_release_logs, self.temp.name)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)
        self.ctx.profile.data["items"] = []
        for text in self.now_texts:
            self.ctx.profile.add_note_item(text)

    def notes(self):
        return copy.deepcopy(self.ctx.profile.data["items"])

    def _model_fixture(self, semantic, text, *, active_context=None):
        """Only the model proposal boundary is stubbed; real Core/worker run.

        This suite covers typed note execution and isolation, NOT live Turkish
        recognition. Every phrase has an explicit independent model fixture;
        unlisted phrases fail rather than silently falling back to a parser.
        """
        queries = {
            "notlarımda proje alfa ara": "proje alfa",
            "proje alfa geçen notu bul": "proje alfa",
            "notlarda toplantı geçenleri göster": "toplantı",
            "hangi notumda bütçe yazıyor": "bütçe",
            "notlarımda zzzzz ara": "zzzzz",
            "notlarımda gizli ara": "gizli",
        }
        if text in queries:
            row = {"which": "search", "query": queries[text]}
            capability = "notes.read"
        elif text in ("notlarımı özetle", "tüm notlarımı özetle"):
            row = {"which": "summary"}
            capability = "notes.read"
        elif text in ("ikinci notumu özetle", "proje alfa başlıklı notu özetle"):
            matches = [ref for ref in semantic.references if ref.kind == "note"]
            if len(matches) != 1:
                raise AssertionError("The note target must be uniquely observed before Core.")
            row = {"which": "summary", "id": matches[0].id}
            capability = "notes.read"
        elif text in ("kitap notunu sil", "kitap notunu düzelt: kitap: Suç ve Ceza"):
            matches = [ref for ref in semantic.references if ref.kind == "note"]
            if len(matches) != 1:
                raise AssertionError("Model cannot invent an unobserved note target.")
            row = {"operation": "delete" if text.endswith(" sil") else "update",
                   "id": matches[0].id}
            if row["operation"] == "update":
                row["text"] = "kitap: Suç ve Ceza"
            capability = "notes.write"
        elif text in ("notlarımda ara", "toplantı notunu özetle", "bu notu özetle"):
            reason = {
                "notlarımda ara": brain_understanding.NOTE_SEARCH_QUERY_MISSING,
                "toplantı notunu özetle": brain_understanding.NOTE_TARGET_AMBIGUOUS,
                "bu notu özetle": brain_understanding.NOTE_TARGET_UNRESOLVED,
            }[text]
            return replace(semantic, request_kind=RequestKind.CLARIFY,
                           capability_hint=None, arguments={"original_text": text},
                           ambiguities=(reason,), needs_input=True, actions=())
        else:
            raise AssertionError(f"No explicit semantic model fixture for {text!r}")
        return replace(
            semantic, request_kind=RequestKind.CAPABILITY,
            capability_hint=capability,
            arguments={"original_text": text, "notes": row},
            ambiguities=(), needs_input=False, actions=(),
        )

    def through_brain(self, text, *, forbid_legacy_search=True, ask=None, owner=None):
        owner = owner or self.owner
        rid = "notes-ss-" + uuid.uuid4().hex[:8]
        requests_state.register(owner, rid)
        handler = Mock(wraps=self.ctx.handle)
        with ExitStack() as stack:
            if forbid_legacy_search:
                from modules import main_planner
                self.assertFalse(hasattr(main_planner, "_note_lookup"),
                                 "Retired raw note lookup must remain physically absent.")
                stack.enter_context(patch.object(
                    brain_entry, "apply_model_understanding",
                    side_effect=self._model_fixture,
                ))
            if ask is not None:
                stack.enter_context(patch.object(self.ctx, "ask", ask))
            stack.enter_context(patch.object(
                self.ctx, "chat", side_effect=AssertionError("notes search/summary sohbet koluna düşmemeli"),
            ))
            stack.enter_context(requests_state.activate(owner, rid))
            entry = brain_entry.prepare(self.ctx, owner=owner, request_id=rid, text=text,
                                        source="yazı", model_understanding=forbid_legacy_search)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handler, text)
        return entry, out, feedback, handler


class EndToEndSearchTests(_BrainCase):
    def test_required_search_phrases_reach_the_notes_domain(self):
        cases = {
            "notlarımda proje alfa ara": ("proje alfa", "proje beta"),
            "proje alfa geçen notu bul": ("proje alfa", "bütçe raporu"),
            "notlarda toplantı geçenleri göster": ("proje alfa", "bütçe raporu"),
            "hangi notumda bütçe yazıyor": ("bütçe raporu", "market: süt"),
        }
        for text, (wanted, unwanted) in cases.items():
            with self.subTest(text=text):
                entry, out, feedback, handler = self.through_brain(text)
                self.assertEqual(entry.understanding.arguments["notes"]["which"], "search", text)
                self.assertIn(wanted, out, text)
                self.assertNotIn(unwanted, out, text)
                self.assertFalse(handler.called, text)
                self.assertEqual(feedback.result_status, "handled", text)

    def test_toplu_phrase_lists_every_matching_note(self):
        _entry, out, _feedback, handler = self.through_brain("notlarda toplantı geçenleri göster")
        self.assertIn("proje alfa toplantı notları", out)
        self.assertIn("Ahmet ile toplantı", out)
        self.assertFalse(handler.called)

    def test_no_match_is_honest_and_shows_note_count(self):
        _entry, out, feedback, handler = self.through_brain("notlarımda zzzzz ara")
        self.assertIn("bulamadım", out)
        self.assertIn(f"{len(self.now_texts)} notun var", out)
        self.assertFalse(handler.called)
        self.assertEqual(feedback.result_status, "handled")

    def test_empty_query_never_executes_a_search(self):
        entry, out, feedback, handler = self.through_brain("notlarımda ara")
        self.assertTrue(entry.understanding.needs_input)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertFalse(handler.called)
        self.assertIn("kelime", out.casefold())

    def test_search_never_mutates_profile_notes(self):
        before = self.notes()
        for text in ("notlarımda proje alfa ara", "hangi notumda bütçe yazıyor", "notlarda toplantı geçenleri göster"):
            self.through_brain(text)
        self.assertEqual(self.notes(), before)

    def test_other_profiles_notes_stay_isolated(self):
        from modules import personalization
        with tempfile.TemporaryDirectory() as other_dir:
            with patch.object(personalization, "USERS_DIR", Path(other_dir)):
                other = personalization.Profile("Baska")
                other.add_note_item("baska kullaniciya ait gizli")
                other.add_note_item("baska ikinci not")
                other.save()
                self.ctx.profile = other
                entry, out, feedback, handler = self.through_brain("notlarımda gizli ara", owner=other.slug)
        self.assertIn("baska kullaniciya ait gizli", out)
        self.assertNotIn("proje alfa", out)
        self.assertFalse(handler.called)
        self.assertEqual(feedback.result_status, "handled")


class EndToEndSummaryTests(_BrainCase):
    def test_all_notes_summary_uses_domain_owner_and_no_chat(self):
        ask = Mock(return_value="Kısa özet: proje ve bütçe.")
        for text in ("notlarımı özetle", "tüm notlarımı özetle"):
            with self.subTest(text=text):
                entry, out, feedback, handler = self.through_brain(text, ask=ask)
                self.assertEqual(entry.understanding.arguments["notes"], {"which": "summary"}, text)
                self.assertEqual(out, "Kısa özet: proje ve bütçe.", text)
                self.assertFalse(handler.called, text)
                self.assertEqual(feedback.result_status, "handled", text)
        prompt = ask.call_args.args[0]
        self.assertIn("proje alfa toplantı notları", prompt)
        self.assertIn("bütçe raporu hazırla", prompt)

    def test_ordinal_summary_sends_only_that_note(self):
        ask = Mock(return_value="İkinci not özeti.")
        entry, out, _feedback, handler = self.through_brain("ikinci notumu özetle", ask=ask)
        self.assertEqual(entry.understanding.arguments["notes"]["which"], "summary")
        self.assertEqual(out, "İkinci not özeti.")
        prompt = ask.call_args.args[0]
        self.assertIn("proje beta fikirleri", prompt)
        self.assertNotIn("proje alfa toplantı notları", prompt)
        self.assertFalse(handler.called)

    def test_named_summary_sends_only_the_resolved_note(self):
        ask = Mock(return_value="Proje notu özeti.")
        _entry, out, _feedback, handler = self.through_brain("proje alfa başlıklı notu özetle", ask=ask)
        self.assertEqual(out, "Proje notu özeti.")
        prompt = ask.call_args.args[0]
        self.assertIn("proje alfa toplantı notları", prompt)
        self.assertNotIn("bütçe raporu", prompt)
        self.assertFalse(handler.called)

    def test_ambiguous_named_summary_asks_and_never_calls_the_model(self):
        ask = Mock(return_value="olmamalı")
        entry, out, feedback, handler = self.through_brain("toplantı notunu özetle", ask=ask)
        self.assertTrue(entry.understanding.needs_input)
        self.assertEqual(feedback.result_status, "needs_input")
        ask.assert_not_called()
        self.assertFalse(handler.called)
        self.assertIn("netleştir", out.casefold())

    def test_deictic_summary_without_context_asks_and_never_calls_the_model(self):
        ask = Mock(return_value="olmamalı")
        entry, out, feedback, handler = self.through_brain("bu notu özetle", ask=ask)
        self.assertTrue(entry.understanding.needs_input)
        self.assertEqual(feedback.result_status, "needs_input")
        ask.assert_not_called()
        self.assertFalse(handler.called)
        self.assertIn("netleştir", out.casefold())

    def test_empty_notebook_summary_does_not_call_the_model(self):
        ask = Mock(return_value="olmamalı")
        self.ctx.profile.data["items"] = []
        _entry, out, feedback, handler = self.through_brain("notlarımı özetle", ask=ask)
        ask.assert_not_called()
        self.assertFalse(handler.called)
        self.assertIn("boş", out.casefold())
        self.assertEqual(feedback.result_status, "handled")

    def test_summary_never_mutates_profile_notes(self):
        before = self.notes()
        ask = Mock(return_value="Özet.")
        self.through_brain("notlarımı özetle", ask=ask)
        self.assertEqual(self.notes(), before)


class RegressionThroughBrainTests(_BrainCase):
    def test_existing_note_commands_keep_working(self):
        from brain_turn_fixture import turn, note_change
        before = len(self.notes())
        out = turn(self.ctx, "not al: market süt", "notes.add", {"text": "market süt"})
        self.assertIn("Not aldım", out)
        self.assertEqual(len(self.notes()), before + 1)
        self.assertIn("Notların", turn(self.ctx, "notlarım", "notes.read", {"notes": {"which": "all"}}))
        self.assertIn("notun var", turn(self.ctx, "kaç notum var", "notes.read", {"notes": {"which": "count"}}))
        first = self.ctx.profile.data["items"][0]
        self.assertIn("Notu sildim", note_change(self.ctx, "1 numaralı notu sil", first, "delete"))
        last = self.ctx.profile.data["items"][-1]
        self.assertIn("Notu sildim", note_change(self.ctx, "son notu sil", last, "delete"))
        self.assertEqual(len(self.notes()), before - 1)

    def test_named_delete_and_update_keep_canonical_ownership(self):
        self.ctx.profile.add_note_item("kitap: Sefiller")
        entry, out, _feedback, handler = self.through_brain("kitap notunu sil", forbid_legacy_search=True)
        self.assertEqual(entry.understanding.capability_hint, "notes.write")
        self.assertIn("Notu sildim", out)
        self.assertFalse(handler.called)
        self.ctx.profile.add_note_item("kitap: Sefiller")
        entry, out, _feedback, handler = self.through_brain(
            "kitap notunu düzelt: kitap: Suç ve Ceza", forbid_legacy_search=True,
        )
        self.assertEqual(entry.understanding.capability_hint, "notes.write")
        self.assertIn("Düzelttim", out)
        self.assertFalse(handler.called)


class StaticSecondAuthorityGuardTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1] / "modules"

    def _tree(self, name):
        return ast.parse((self.root / name).read_text(encoding="utf-8"))

    @staticmethod
    def _function(tree, name):
        return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)

    @staticmethod
    def _names(node):
        out = set()
        for item in ast.walk(node):
            if isinstance(item, ast.Name):
                out.add(item.id)
            elif isinstance(item, ast.Attribute):
                out.add(item.attr)
        return out

    def test_legacy_lookup_keeps_no_search_execution(self):
        tree = self._tree("main_planner.py")
        module_names = {node.name for node in ast.walk(tree)
                        if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        self.assertNotIn("_note_lookup", module_names)
        self.assertNotIn("_NOTE_ASK_END", {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)})
        self.assertIn("notes_search", module_names)
        self.assertIn("notes_summary", module_names)

    def test_semantic_extraction_lives_only_in_understanding(self):
        tree = self._tree("brain_understanding.py")
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        for name in ("_notes_search_arguments", "_notes_summary_request", "_notes_request_kind"):
            self.assertIn(name, functions)
        imports = {
            alias.name
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertNotIn("main_planner", imports)
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and (node.module or "").endswith("main_planner")
                             for node in ast.walk(tree)))

    def test_core_intent_is_the_only_execution_entry(self):
        tree = self._tree("engine_intents.py")
        dispatch = self._function(tree, "dispatch")
        names = self._names(dispatch)
        self.assertIn("notes_search", names)
        self.assertIn("notes_summary", names)
        self.assertNotIn("_note_lookup", names)

    def test_notes_partial_hint_cannot_return(self):
        self.assertNotIn("notes.read", brain_core_map.PARTIAL_CORE_HINTS)
        self.assertNotIn("notes.read", brain_core_map.LEGACY_OWNED_HINTS)
        plan = brain_core_map.core_plan("notes.read", {"notes": {"which": "search", "query": "proje"}})
        self.assertEqual(plan, ("notes_read", {"which": "search", "query": "proje"}))


if __name__ == "__main__":
    unittest.main()
