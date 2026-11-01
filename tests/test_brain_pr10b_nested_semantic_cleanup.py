"""PR10b: bir kullanıcı isteğinin canonical semantic kararı bir kez üretilir.

Nested (çok adımlı / kısayol) adımlar ikinci bir Understanding, router veya resolver gibi
çalışamaz; eski çeviri kaynak-seçimi (`chat_translation`) ve dosya hedef-seçimi
(`doc_* / _resolve_doc`) yolları Production'da çağıranı olmayan ikinci yetkidir.
"""
import ast
import importlib.util
import pathlib
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_brain_production_entry as fx
from modules import (brain_entry, brain_gates, command_manager, engine_runtime, engine_sequence,
                     main_planner, requests_state)
from modules.command_manager import PENDING_INPUT_FIELDS

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"
# Production kaynakları: motor modülleri ve kök uygulama dosyaları (web_chat gibi gerçek çağıranlar burada durur).
PRODUCTION_SOURCES = (*sorted(MODULES.glob("*.py")), *sorted(ROOT.glob("*.py")))
# Geliştirme kabul aracı; gerçek bir kullanıcı turn'ü değildir ve semantic authority taşımaz.
NON_PRODUCTION_HANDLERS = {"acceptance_checks.py"}
# PR10b ile emekli edilen ikinci semantic authority adları.
RETIRED = ("chat_translation",)


def _source(name: str) -> str:
    return (MODULES / name).read_text(encoding="utf-8")


def _referencing(pattern: str) -> set[str]:
    import re
    rx = re.compile(pattern)
    return {path.name for path in MODULES.glob("*.py") if rx.search(path.read_text(encoding="utf-8"))}


def _runtime_handle_calls() -> list[tuple[str, int]]:
    """`runtime.handle(...)` ÇAĞRILARI. handoff'a argüman olarak geçen `runtime.handle` çağrı değildir."""
    rows = []
    for path in PRODUCTION_SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "handle"):
                continue
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in {"runtime", "self", "context", "ctx"}:
                rows.append((path.name, node.lineno))
    return rows


def _gate(owner: str, request_id: str, gate: str, reason: str) -> brain_gates.GateObservation:
    return brain_gates.GateObservation(owner=owner, request_id=request_id, gate=gate,
                                       matched=False, reason_code=reason)


def _entry(text: str, *, owner: str, request_id: str = "pr10b-entry", understanding=None) -> brain_entry.EntryResult:
    return brain_entry.EntryResult(
        owner=owner, request_id=request_id, source="yazı", text=text,
        active_context=fx.context(owner=owner, request_id=request_id),
        state_gate=_gate(owner, request_id, "state", "NO_BOUNDED_STATE_MATCH"),
        fast_gate=_gate(owner, request_id, "fast", "NO_EXACT_FAST_MATCH"),
        understanding=understanding)


class EngineFixture(unittest.TestCase):
    """Gerçek EngineContext; classifier her zaman kapalıdır (ikinci semantic authority yasak)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        classifier = patch("modules.router.classify", side_effect=AssertionError("router.classify ikinci semantic authority olarak çağrıldı"))
        classifier.start()
        self.addCleanup(classifier.stop)

    def prepare(self, text: str):
        rid = "pr10b-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            return brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")


class NestedStepBoundaryTests(EngineFixture):
    """A + E: bağlı canonical entry yalnız kendi metnini taşır; adım metnine hiçbir karar devredilmez."""

    SEQUENCE = "ankara'da hava nasıl ardından sesi 30 yap"

    def setUp(self):
        super().setUp()
        brain_entry._install_core_guards(self.ctx)
        self.entry = self.prepare(self.SEQUENCE)
        self.parent = brain_entry._legacy_route_projection(self.entry)

    def test_bound_entry_projects_only_its_own_text(self):
        with brain_entry.bind(self.entry):
            self.assertEqual(self.ctx.route(self.entry.text), self.parent)

    def test_nested_step_never_receives_the_parents_decision(self):
        with brain_entry.bind(self.entry):
            step = self.ctx.route("sesi 30 yap")
        self.assertIsInstance(step, dict)
        self.assertEqual(step["intent"], "clarify")
        self.assertEqual(set(step["args"]), {"question"})
        self.assertNotEqual(step, self.parent)
        self.assertNotIn("hava", str(step["args"]).lower())

    def test_nested_step_refusal_is_closed_and_carries_no_target(self):
        with brain_entry.bind(self.entry):
            first = self.ctx.route("raporu özetle")
            second = self.ctx.route("sesi 30 yap")
        for row in (first, second):
            self.assertEqual(row["intent"], "clarify")
            self.assertEqual(set(row["args"]), {"question"})
            self.assertNotIn("path", row["args"])
            self.assertIn("adım", str(row["args"]["question"]).lower())

    def test_typo_corrected_rerun_of_the_same_request_is_not_a_step(self):
        # handle_request'ın TEK açık yeniden geçişi aynı istektir; adım reddi değil, canonical izdüşümünü alır.
        self.ctx._typo_pass, self.ctx._typo_orig = True, self.entry.text
        self.addCleanup(setattr, self.ctx, "_typo_pass", False)
        self.addCleanup(setattr, self.ctx, "_typo_orig", "")
        with brain_entry.bind(self.entry):
            self.assertEqual(self.ctx.route("ankara'da hava nasıl ardından sesi 30"), self.parent)

    def test_legacy_door_is_the_only_classifier_caller(self):
        legacy = getattr(self.ctx, "_brain_legacy_route", None)
        self.assertTrue(callable(legacy))
        with patch("modules.router.classify", return_value={"intent": "chat", "args": {}}) as classify:
            self.assertEqual(legacy("sesi 30 yap")["intent"], "chat")
        classify.assert_called_once()


class CanonicalFileTargetTests(EngineFixture):
    """C: canonical dosya isteği hedefi `_resolve_doc` ile tekrar seçmez."""

    def setUp(self):
        super().setUp()
        from modules import nxapi
        self.file = Path(self.temp.name) / "rapor.txt"
        self.file.write_text("içerik", encoding="utf-8")
        rows = [{"path": str(self.file), "name": "rapor.txt", "ext": ".txt"}]
        original = brain_entry.build_candidates
        candidate = patch.object(brain_entry, "build_candidates",
                                 lambda **kw: original(**{**kw, "file_reader": lambda *, limit: rows[:limit]}))
        candidate.start()
        self.addCleanup(candidate.stop)
        roots = patch.object(nxapi, "_roots", return_value=[Path(self.temp.name)])
        roots.start()
        self.addCleanup(roots.stop)
        self.ctx.docs = SimpleNamespace(summarize=Mock(return_value="ÖZET"), insights=Mock(return_value="ANALİZ"))

    def through_brain(self, text: str):
        rid = "pr10b-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            with patch("modules.brain_precedence.claim", return_value=None):
                out, _feedback, _job = brain_entry.handoff(self.ctx, entry, self.ctx.handle, text)
        return entry, out

    def test_canonical_summary_uses_the_resolved_reference_and_no_legacy_resolver(self):
        with patch.object(self.ctx, "_resolve_doc", side_effect=AssertionError("canonical hedef tekrar seçilemez")):
            entry, out = self.through_brain("rapor.txt dosyasını özetle")
        self.assertEqual(brain_entry.core_plan(entry), ("file_action", {"operation": "summarize", "path": str(self.file)}))
        self.assertIn("ÖZET", out)
        self.assertEqual(Path(self.ctx.docs.summarize.call_args.args[0]).resolve(), self.file.resolve())

    def test_ambiguous_file_request_never_guesses_a_path(self):
        with patch.object(self.ctx, "_resolve_doc", side_effect=AssertionError("belirsiz istek tahmin edemez")):
            entry, out = self.through_brain("dosyayı özetle")
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("Hangi dosyayı", out)

    def test_legacy_resolve_doc_is_reachable_only_from_the_legacy_route_chain(self):
        self.assertEqual(_referencing(r"\._resolve_doc\("), {"engine_intents.py", "engine_tools.py"})
        for name in ("engine_sequence.py", "main_planner.py", "command_manager.py", "brain_entry.py", "brain_core_map.py"):
            self.assertNotIn("_resolve_doc", _source(name))

    def test_doc_intents_have_no_canonical_producer(self):
        self.assertEqual(_referencing(r'"doc_(summary|insight|convert|translate)"'),
                         {"engine_intents.py", "router.py"})
        self.assertNotIn("doc_", _source("brain_core_map.py"))


class CanonicalTranslationAuthorityTests(unittest.TestCase):
    """D: çeviride kaynak seçimi tek başına Reference Resolver'a aittir."""

    def test_legacy_translation_authority_is_retired(self):
        self.assertIsNone(importlib.util.find_spec("modules.chat_translation"))
        self.assertEqual(_referencing(r"chat_translation"), set())

    def test_dispatch_does_not_select_a_translation_source(self):
        calls = []
        session = SimpleNamespace(**{name: None for name in PENDING_INPUT_FIELDS}, last_doc=None, speech_override=None)
        context = command_manager.CommandContext(
            profile=SimpleNamespace(slug="hamdi"), session=session, emit=Mock(), table_chat=Mock(),
            history_read=lambda *a, **k: calls.append(a) or [], study_intent=Mock(return_value=None),
            pc_owner=lambda: "hamdi", source="yazı")
        with patch("modules.visual_chat.handle", return_value=None), \
             patch("modules.usage_meter.handle", return_value=None), \
             patch("modules.smart_router.handle", return_value=None), \
             patch("modules.system_doctor.handle", return_value=None), \
             patch("modules.task_agents.handle", return_value=None), \
             patch("modules.pc_guide.handle", return_value=None), \
             patch("modules.developer.handle", return_value=None), \
             patch("modules.desktop_agent.handle", return_value=None):
            result = command_manager.dispatch(context, "bunu türkçeye çevir", "bunu türkçeye çevir")
        self.assertIsNone(result)
        self.assertEqual(calls, [])
        self.assertIsNone(session.last_doc)

    def test_shared_grammar_stays_with_the_canonical_understanding(self):
        self.assertIn("translation_request", _source("brain_understanding.py"))
        self.assertEqual(_referencing(r"translation_request") - {"brain_understanding.py", "translation_request.py", "finance.py"}, set())


class NestedExecutionTests(unittest.TestCase):
    """B + F: nested runner adım metnini yeniden yorumlamaz ve effect üretmez."""

    def setUp(self):
        self.session = SimpleNamespace(**{name: None for name in PENDING_INPUT_FIELDS},
                                       _in_multi=False, _in_macro=False, speech_override="eski adım sesi")
        self.runtime = SimpleNamespace(
            re=__import__("re"), _tr_lower=lambda text: text.replace("İ", "i").replace("I", "ı").lower(),
            _session=Mock(return_value=self.session), profile=SimpleNamespace(slug="hamdi", data={}),
            flags={}, stop_event=Mock(is_set=Mock(return_value=False)),
            handle=Mock(side_effect=AssertionError("nested adım runtime.handle ile yeniden yorumlanamaz")),
            events=SimpleNamespace(put=Mock()), privacy=SimpleNamespace(audit=Mock()),
            requests_state=SimpleNamespace(check=Mock()),
            docs=SimpleNamespace(summarize=Mock()), output=SimpleNamespace(convert_document=Mock()),
            system_control=SimpleNamespace(find_app=Mock(return_value=None), open_application=Mock(return_value="açıldı")))

    def test_no_production_module_reinterprets_a_step_through_handle(self):
        self.assertEqual([(name, line) for name, line in _runtime_handle_calls() if name not in NON_PRODUCTION_HANDLERS], [])

    def test_runtime_handle_binding_stays_the_single_user_turn_entry(self):
        self.assertEqual({name for name, _ in _runtime_handle_calls()}, NON_PRODUCTION_HANDLERS)

    def test_run_steps_executes_no_effect_and_returns_a_closed_answer(self):
        out = engine_sequence._run_steps(self.runtime, ["sesi 30 yap", "raporu özetle"])
        self.assertIsInstance(out, str)
        self.runtime.privacy.audit.assert_called_once()
        self.runtime.docs.summarize.assert_not_called()
        self.runtime.output.convert_document.assert_not_called()
        self.runtime.events.put.assert_not_called()
        self.runtime.system_control.open_application.assert_not_called()
        self.assertIs(self.session._in_multi, False)

    def test_run_steps_neither_prepares_a_second_entry_nor_classifies(self):
        with patch.object(brain_entry, "prepare", side_effect=AssertionError("ikinci canonical entry yok")), \
             patch("modules.router.classify", side_effect=AssertionError("ikinci classifier yok")), \
             patch("modules.app_actions.reference_context", side_effect=AssertionError("legacy reference resolver yok")):
            out = engine_sequence._run_steps(self.runtime, ["sesi 30 yap", "notları aç"])
        self.assertIn("sesi 30 yap", out)

    def test_run_steps_refuses_without_inventing_a_step_result(self):
        out = engine_sequence._run_steps(self.runtime, ["sesi 30 yap", "raporu özetle"])
        for fragment in ("yapamadım", "açtım", "ÖZET"):
            self.assertNotIn(fragment, out)

    def _macro_runtime(self, actions):
        runtime = self.runtime
        runtime.profile.data["macros"] = {"kısayol": {"title": "kısayol", "actions": actions}}
        runtime._macro_key = lambda text: text.strip().strip(".!?")
        runtime._VERB_END = runtime.re.compile(r"\s*(aç|başlat|çalıştır)\b")
        runtime.time = SimpleNamespace(sleep=Mock())
        return runtime

    def test_macro_never_reinterprets_its_actions(self):
        runtime = self._macro_runtime(["chrome aç"])
        with patch.object(brain_entry, "prepare", side_effect=AssertionError("ikinci canonical entry yok")), \
             patch("modules.router.classify", side_effect=AssertionError("ikinci classifier yok")):
            out = main_planner._macro_run(runtime, "kısayol")
        self.assertIsInstance(out, str)
        self.assertIs(self.session._in_macro, False)

    def test_macro_runs_only_the_deterministic_app_owner(self):
        runtime = self._macro_runtime(["chrome aç"])
        runtime.system_control.find_app = Mock(return_value="Chrome")
        out = main_planner._macro_run(runtime, "kısayol")
        runtime.system_control.open_application.assert_called_once_with("Chrome")
        self.assertIn("kısayol", out)

    def test_macro_refuses_actions_that_would_need_interpretation(self):
        runtime = self._macro_runtime(["sesi kıs"])
        out = main_planner._macro_run(runtime, "kısayol")
        runtime.system_control.open_application.assert_not_called()
        self.assertIn("sesi kıs", out)

    def test_macro_keeps_every_effect_guard(self):
        runtime = self._macro_runtime(["chrome aç", "spotify aç"])
        runtime.system_control.find_app = Mock(side_effect=lambda base: "Chrome" if "chrome" in base else "Spotify")
        self.session.pending_confirm = {"soru": "onay?"}
        out = main_planner._macro_run(runtime, "kısayol")
        self.assertEqual(runtime.system_control.open_application.call_count, 1)
        self.assertIn("yanıt", out)
        self.assertIs(self.session._in_macro, False)

    def test_target_stability_during_nested_execution(self):
        owner = "hamdi"
        entry = _entry("rapor.txt dosyasını özetle ardından sesi kıs", owner=owner,
                       understanding=fx.understanding(owner=owner, request_id="pr10b-entry",
                                                      kind=fx.RequestKind.CAPABILITY, hint="files.read"))
        before = entry.references
        with brain_entry.bind(entry):
            step = brain_entry.current()
        self.assertIs(step, entry)
        self.assertEqual(entry.references, before)
        self.assertEqual(entry.text, "rapor.txt dosyasını özetle ardından sesi kıs")


class AuthorityInvariantsTests(EngineFixture):
    """F + PR10a: korunan sınırlar ve PR10a sabitleri yerinde duruyor."""

    def test_core_guards_are_installed_once(self):
        brain_entry._install_core_guards(self.ctx)
        route, control = self.ctx.route, command_manager.engine_control
        brain_entry._install_core_guards(self.ctx)
        self.assertIs(self.ctx.route, route)
        self.assertIs(command_manager.engine_control, control)
        self.assertTrue(getattr(self.ctx, "_brain_route_guard_installed", False))

    def test_engine_control_still_requires_an_exact_canonical_fast_match(self):
        brain_entry._install_core_guards(self.ctx)
        entry = _entry("jarvis kapat", owner=self.owner)
        with brain_entry.bind(entry):
            self.assertIs(brain_entry.allow_legacy_engine_control(), False)
            self.assertIs(command_manager.engine_control("jarvis kapat", source="yazı", sleeping=False,
                                                         close=Mock(), set_sleep=Mock()), None)

    def test_pr10a_invariants_hold(self):
        from modules import engine_live_brain, engine_voice
        self.assertFalse(hasattr(engine_voice, "_live_command"))
        self.assertTrue(callable(engine_live_brain._live_command))
        self.assertNotIn("work_modes", _source("goal_executor.py"))


class CallerZeroGuardTests(unittest.TestCase):
    """G: emekli edilen yetkilere yeni production çağıran eklenirse bu test düşer."""

    def test_retired_authorities_have_no_production_caller(self):
        for name in RETIRED:
            self.assertEqual(_referencing(rf"\b{name}\b"), set(), name)

    def test_nested_runners_do_not_import_the_legacy_semantic_chain(self):
        for name in ("engine_sequence.py", "main_planner.py", "command_manager.py"):
            source = _source(name)
            for legacy in (r"\brouter\b", r"\bintent_router\b", r"\bwork_modes\b", r"\bfreshness\b", r"\breference_context\b"):
                self.assertNotRegex(source, legacy, (name, legacy))

    def test_classifier_has_only_the_unbound_legacy_route_door(self):
        self.assertEqual(_referencing(r"intent_router\.classify"), {"engine_tools.py"})


if __name__ == "__main__":
    unittest.main()
