"""PR10b: bir kullanıcı isteğinin canonical semantic kararı bir kez üretilir.

Nested (çok adımlı / kısayol) adımlar ikinci bir Understanding, router veya resolver gibi
çalışamaz; eski çeviri kaynak-seçimi (`chat_translation`) ve dosya hedef-seçimi
(`doc_* / _resolve_doc`) yolları Production'da çağıranı olmayan ikinci yetkidir.
"""
import ast
import importlib.util
import inspect
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
# Kabul aracı da prepare/handoff kullanır; doğrudan runtime.handle istisnası kalmadı.
NON_PRODUCTION_HANDLERS = set()
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


class _Feedback:
    """BrainFeedback'ın runner'ın baktığı tek alanı; adımın gerçek result_status'unu taşır."""

    def __init__(self, result_status: str):
        self.result_status = result_status


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
    """Gerçek EngineContext; ikinci semantic authority fiziksel olarak yoktur (aşağıdaki muhafız)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug

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
            self.assertEqual(brain_entry.route_command(self.ctx, self.entry.text), self.parent)

    def test_nested_step_never_receives_the_parents_decision(self):
        with brain_entry.bind(self.entry):
            step = brain_entry.route_command(self.ctx, "sesi 30 yap")
        self.assertIsInstance(step, dict)
        self.assertEqual(step["intent"], "clarify")
        self.assertEqual(set(step["args"]), {"question"})
        self.assertNotEqual(step, self.parent)
        self.assertNotIn("hava", str(step["args"]).lower())

    def test_nested_step_refusal_is_closed_and_carries_no_target(self):
        with brain_entry.bind(self.entry):
            first = brain_entry.route_command(self.ctx, "raporu özetle")
            second = brain_entry.route_command(self.ctx, "sesi 30 yap")
        for row in (first, second):
            self.assertEqual(row["intent"], "clarify")
            self.assertEqual(set(row["args"]), {"question"})
            self.assertNotIn("path", row["args"])
            self.assertIn("adım", str(row["args"]["question"]).lower())

    def test_the_nested_step_refusal_has_no_turn_flag_escape(self):
        # BRAIN-MIG-042 (§25 A): aynı request içinde ikinci bir geçiş yoktur. Adım reddi tur
        # bayraklarına bakmaz; bağlı cümleden farklı gelen her metin addır.
        self.assertNotIn("runtime", inspect.signature(brain_entry.nested_step).parameters)
        with brain_entry.bind(self.entry):
            self.assertNotEqual(
                brain_entry.route_command(self.ctx, "ankara'da hava nasıl ardından sesi 30"), self.parent)

    def test_legacy_door_projects_the_bound_turn_without_any_classifier(self):
        # PR10c: classifier kapısı fiziksel olarak kalktı; route kapısı yalnız bağlı turn'ü izdüşürür.
        self.assertEqual(_referencing(r"intent_router\.classify\(|router\.classify\("), set())
        legacy = getattr(brain_entry, "_legacy_route_projection")
        with brain_entry.bind(self.entry):
            self.assertEqual(legacy(self.entry), self.parent)


class CanonicalFileTargetTests(EngineFixture):
    """C: canonical dosya isteği hedefi ikinci bir resolver ile tekrar seçmez."""

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
        # Emekli ikinci hedef seçici fiziksel olarak yok; `patch.object` kurulamaz olur.
        self.assertFalse(hasattr(type(self.ctx), "_resolve_doc"))
        self.assertFalse(hasattr(self.ctx, "_resolve_doc"))
        entry, out = self.through_brain("rapor.txt dosyasını özetle")
        self.assertEqual(brain_entry.core_plan(entry), ("file_action", {"operation": "summarize", "path": str(self.file)}))
        self.assertIn("ÖZET", out)
        self.assertEqual(Path(self.ctx.docs.summarize.call_args.args[0]).resolve(), self.file.resolve())

    def test_ambiguous_file_request_never_guesses_a_path(self):
        entry, out = self.through_brain("dosyayı özetle")
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("Hangi dosyayı", out)

    def test_legacy_file_target_resolver_is_physically_gone(self):
        self.assertEqual(_referencing(r"_resolve_doc"), set())
        self.assertEqual(_referencing(r"reference_context\("), set())

    def test_doc_intents_have_no_canonical_producer(self):
        self.assertEqual(_referencing(r'"doc_(summary|insight|convert|translate)"'), set())
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
            history_read=lambda *a, **k: calls.append(a) or [],
            conversation_summary=Mock(return_value="Kısaca: …"),
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
    """B + F: nested runner adımı canonical envelope ile çalıştırır, ham adımı eski zincire sokmaz."""

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

    def run_steps(self, steps, replies):
        """run_step'i taklit ederek _run_steps'in envelope sözleşmesini ölçer."""
        calls = []

        def fake_run_step(runtime, text):
            calls.append(text)
            return replies[text]
        with patch.object(brain_entry, "run_step", side_effect=fake_run_step):
            out = engine_sequence._run_steps(self.runtime, steps)
        return calls, out

    def test_no_production_module_reinterprets_a_step_through_handle(self):
        self.assertEqual([(name, line) for name, line in _runtime_handle_calls() if name not in NON_PRODUCTION_HANDLERS], [])

    def test_runtime_handle_binding_stays_the_single_user_turn_entry(self):
        self.assertEqual({name for name, _ in _runtime_handle_calls()}, NON_PRODUCTION_HANDLERS)

    def test_steps_run_in_order_each_with_its_own_canonical_entry(self):
        calls, out = self.run_steps(["sesi 30 yap", "raporu özetle"],
                                    {"sesi 30 yap": ("Ses 30.", _Feedback("handled")),
                                     "raporu özetle": ("ÖZET", _Feedback("handled"))})
        self.assertEqual(calls, ["sesi 30 yap", "raporu özetle"])
        self.assertEqual(out.splitlines(), ["1. Ses 30.", "2. ÖZET"])
        self.runtime.privacy.audit.assert_called_once_with("çok adımlı komut", "2 adım")

    def test_run_steps_never_touches_the_legacy_semantic_chain(self):
        with patch.object(brain_entry, "run_step", return_value=("tamam", _Feedback("handled"))) as step, \
             patch("modules.engine_intents.dispatch", side_effect=AssertionError("adım envelope dışından dispatch edilemez")):
            engine_sequence._run_steps(self.runtime, ["sesi 30 yap", "notları aç"])
        self.assertEqual([c.args[1] for c in step.call_args_list], ["sesi 30 yap", "notları aç"])
        self.runtime.handle.assert_not_called()
        self.runtime.handle.assert_not_called()

    def test_unverified_step_result_stops_dependent_steps(self):
        class Verified(str):
            ok = False
        calls, out = self.run_steps(["ilk", "ikinci"],
                                    {"ilk": (Verified("doğrulanmadı"), _Feedback("handled")),
                                     "ikinci": ("çalışmamalı", _Feedback("handled"))})
        self.assertEqual(calls, ["ilk"])
        self.assertIn("doğrulanamadı", out)
        self.assertNotIn("çalışmamalı", out)

    def test_step_awaiting_input_or_clarification_stops_dependent_steps(self):
        for status in ("needs_input", "failed", "cancelled"):
            with self.subTest(status=status):
                self.runtime.privacy.audit.reset_mock()
                calls, out = self.run_steps(["ilk", "ikinci"],
                                            {"ilk": ("bekliyor", _Feedback(status)),
                                             "ikinci": ("çalışmamalı", _Feedback("handled"))})
                self.assertEqual(calls, ["ilk"])
                self.assertIn("kalan adımları", out)
                self.assertNotIn("çalışmamalı", out)

    def test_closing_owner_change_and_pending_answer_keep_their_boundaries(self):
        self.runtime.flags["closing"] = True
        _calls, out = self.run_steps(["ilk"], {"ilk": ("çalışmamalı", _Feedback("handled"))})
        self.assertIn("Jarvis kapanıyor", out)
        self.runtime.privacy.audit.assert_called_once_with("çok adımlı komut", "1 adım")

        self.runtime.flags.clear()
        def switch_owner(runtime, text):
            self.runtime.profile.slug = "ebru"
            return ("ilk", _Feedback("handled"))
        with patch.object(brain_entry, "run_step", side_effect=switch_owner):
            out = engine_sequence._run_steps(self.runtime, ["ilk", "ikinci"])
        self.assertIn("Kullanıcı değişti", out)
        self.assertNotIn("ikinci", out)

        self.runtime.profile.slug = "hamdi"
        self.session.pending_confirm = {"soru": "onay?"}
        _calls, out = self.run_steps(["ilk", "ikinci"], {"ilk": ("onay bekle", _Feedback("handled")),
                                                        "ikinci": ("çalışmamalı", _Feedback("handled"))})
        self.assertIn("yanıt veya onay bekliyor", out)
        self.assertNotIn("çalışmamalı", out)
        self.assertEqual(self.session.pending_confirm, {"soru": "onay?"})

    def test_run_steps_leaves_the_multi_step_marker_and_single_step_speech_behind(self):
        def step(runtime, text):
            self.session.speech_override = "yalnız bu adımın sesi"
            return ("cevap", _Feedback("handled"))
        with patch.object(brain_entry, "run_step", side_effect=step):
            engine_sequence._run_steps(self.runtime, ["bir", "iki"])
        self.assertIs(self.session._in_multi, False)
        self.assertIsNone(self.session.speech_override)

    def test_run_steps_empty_list_audits_zero_steps_and_invents_nothing(self):
        calls, out = self.run_steps([], {})
        self.assertEqual(calls, [])
        self.assertEqual(out, "")
        self.runtime.privacy.audit.assert_called_once_with("çok adımlı komut", "0 adım")

    def test_run_steps_invalid_container_raises_without_running_a_step(self):
        for steps in (None, 123, True):
            with self.subTest(steps=steps), patch.object(brain_entry, "run_step",
                                                         side_effect=AssertionError("adım çalışmamalı")):
                with self.assertRaises(TypeError):
                    engine_sequence._run_steps(self.runtime, steps)
        self.runtime.privacy.audit.assert_not_called()
        self.assertIs(self.session._in_multi, False)

    def _macro_runtime(self, actions):
        runtime = self.runtime
        runtime.profile.data["macros"] = {"kısayol": {"title": "kısayol", "actions": actions}}
        runtime._macro_key = lambda text: text.strip().strip(".!?")
        runtime._VERB_END = runtime.re.compile(r"\s*(aç|başlat|çalıştır)\b")
        runtime.time = SimpleNamespace(sleep=Mock())
        return runtime

    def test_macro_runs_every_action_through_the_canonical_envelope(self):
        runtime = self._macro_runtime(["chrome aç", "sesi kıs"])
        seen = []

        def fake_run_step(rt, text):
            seen.append(text)
            return (f"{text} tamam", _Feedback("handled"))
        with patch.object(brain_entry, "run_step", side_effect=fake_run_step), \
             patch("modules.engine_intents.dispatch", side_effect=AssertionError("kısayol adımı envelope dışından dispatch edilemez")):
            out = main_planner._macro_run(runtime, "kısayol")
        self.assertEqual(seen, ["chrome aç", "sesi kıs"])
        self.assertIn("kısayol", out)
        runtime.handle.assert_not_called()
        runtime.system_control.open_application.assert_not_called()
        self.assertIs(self.session._in_macro, False)

    def test_macro_waits_only_between_its_actions(self):
        runtime = self._macro_runtime(["bir", "iki"])
        with patch.object(brain_entry, "run_step", return_value=("tamam", _Feedback("handled"))):
            main_planner._macro_run(runtime, "kısayol")
        runtime.time.sleep.assert_called_once_with(0.4)

    def test_macro_keeps_every_effect_guard(self):
        runtime = self._macro_runtime(["chrome aç", "spotify aç"])
        self.session.pending_confirm = {"soru": "onay?"}
        with patch.object(brain_entry, "run_step", return_value=("açıldı", _Feedback("handled"))) as step:
            out = main_planner._macro_run(runtime, "kısayol")
        step.assert_called_once_with(runtime, "chrome aç")
        self.assertIn("yanıt veya onay bekliyor", out)
        self.assertIs(self.session._in_macro, False)

    def test_macro_stops_when_a_step_is_not_completed(self):
        runtime = self._macro_runtime(["chrome aç", "spotify aç"])
        with patch.object(brain_entry, "run_step", side_effect=[("soru", _Feedback("needs_input")),
                                                                ("çalışmamalı", _Feedback("handled"))]) as step:
            out = main_planner._macro_run(runtime, "kısayol")
        step.assert_called_once()
        self.assertNotIn("spotify aç tamam", out)
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


class PerStepEnvelopeIdentityTests(EngineFixture):
    """B: run_step adımını KENDİ canonical kararıyla çalıştırır; outer cümlenin kararı ödünç verilmez.

    Gerçek EngineContext, gerçek `prepare`/`handoff`/route guard; yalnız effect taşıyan son adımlar
    (dispatch ve handler) gözlemlenir. Böylece adım, kullanıcıyı tek başına söylediği turn'le
    birebir aynı zincire girer ve hiçbir gerçek effect çalışmaz."""

    SEQUENCE = "ankara'da hava nasıl ardından sesi 30 yap"
    STEP = "sesi 30 yap"

    def setUp(self):
        super().setUp()
        # Bu sınıf gerçek motoru çalıştırır: hiçbir effect makineye dokunamaz.
        effects = patch("modules.system_control.set_volume",
                        side_effect=AssertionError("test effect çalıştıramaz"))
        effects.start()
        self.addCleanup(effects.stop)
        self.rid = "pr10b-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, self.rid)
        activation = requests_state.activate(self.owner, self.rid)
        activation.__enter__()
        self.addCleanup(activation.__exit__, None, None, None)
        self.outer = brain_entry.prepare(self.ctx, owner=self.owner, request_id=self.rid,
                                         text=self.SEQUENCE, source="yazı")
        self.parent = brain_entry._legacy_route_projection(self.outer)
        from dataclasses import replace
        from modules.brain_contracts import RequestKind
        def model(current, text, *, active_context=None):
            capability, arguments = {
                'sesi 30 yap': ('pc.level.set', {'property': 'volume', 'level': 30}),
                'notları aç': ('notes.read', {'notes': {'which': 'all'}}),
            }[text]
            return replace(current, request_kind=RequestKind.CAPABILITY,
                           capability_hint=capability, arguments=arguments,
                           ambiguities=(), needs_input=False)
        transport = patch.object(brain_entry, 'apply_model_understanding', side_effect=model)
        transport.start(); self.addCleanup(transport.stop)

    def observe(self, text, *, bind_outer=True, handle=None):
        """run_step'in adım için kurduğu canonical kararı kaydeder; effect'ler stub'lıdır."""
        seen = []

        def note(kind, command, intent=None):
            seen.append({"kind": kind, "command": command, "intent": intent,
                         "entry": brain_entry.current(), "route": brain_entry.route_command(self.ctx, command)})

        def dispatch_spy(runtime, intent, args, command, lower):
            note("dispatch", command, intent)
            return "DISPATCH"

        def handler(command):
            note("handler", command)
            return "HANDLER"

        with patch("modules.engine_intents.dispatch", side_effect=dispatch_spy), \
             patch("modules.brain_precedence.claim", return_value=None), \
             patch.object(self.ctx, "handle", side_effect=handle or handler):
            if bind_outer:
                with brain_entry.bind(self.outer):
                    out, feedback = brain_entry.run_step(self.ctx, text)
            else:
                out, feedback = brain_entry.run_step(self.ctx, text)
        return seen, out, feedback

    def test_the_step_is_decided_for_itself(self):
        seen, out, feedback = self.observe(self.STEP)
        self.assertTrue(seen, "adım hiçbir canonical yola ulaşmadı")
        for row in seen:
            self.assertEqual(row["command"], self.STEP)
            self.assertIsNot(row["entry"], self.outer)
            self.assertEqual(row["entry"].text, self.STEP)
            self.assertEqual((row["entry"].owner, row["entry"].request_id), (self.owner, self.rid))
            self.assertNotEqual(row["entry"].text, self.SEQUENCE)
        self.assertIn(out, ("DISPATCH", "HANDLER"))
        self.assertEqual((feedback.owner, feedback.request_id), (self.owner, self.rid))

    def test_the_parents_decision_is_never_borrowed_by_the_step(self):
        seen, _out, _feedback = self.observe(self.STEP)
        for row in seen:
            self.assertEqual(row["route"], brain_entry._legacy_route_projection(row["entry"]))
            self.assertNotEqual(row["route"], self.parent)

    def test_the_step_never_falls_back_to_the_legacy_classifier(self):
        # Adımın route kapısı yalnız kendi bağlı entry'sini izdüşürür; dışarıdan karar borç alınmaz
        # ve emekli classifier'a dönüş yolu kalmamıştır.
        seen, _out, _feedback = self.observe(self.STEP)
        self.assertTrue(seen, "adım hiçbir canonical yola ulaşmadı")
        for row in seen:
            self.assertEqual(row["entry"].text, self.STEP)
            self.assertEqual(row["route"], brain_entry._legacy_route_projection(row["entry"]))
        self.assertEqual(_referencing(r"\bintent_router\.classify\("), set())

    def test_a_step_without_a_bound_canonical_entry_is_refused(self):
        with self.assertRaisesRegex(ValueError, "bağlı"):
            brain_entry.run_step(self.ctx, self.STEP)

    def test_the_outer_sentence_cannot_be_re_run_as_its_own_step(self):
        with self.assertRaisesRegex(ValueError, "Outer cümlenin"):
            self.observe(self.SEQUENCE)

    def test_a_blank_step_is_refused(self):
        for blank in ("", "   ", "\n"):
            with self.subTest(blank=blank), self.assertRaisesRegex(ValueError, "boş"):
                self.observe(blank)

    def test_a_step_owned_by_another_profile_is_refused(self):
        other = _entry(self.SEQUENCE, owner="diğer-profil", request_id=self.rid)
        handler = Mock(side_effect=AssertionError("foreign owner adımı çalışamaz"))
        with patch.object(self.ctx, "handle", handler), \
             patch("modules.engine_intents.dispatch", side_effect=AssertionError("foreign owner adımı çalışamaz")), \
             patch("modules.brain_precedence.claim", side_effect=AssertionError("foreign owner adımı çalışamaz")):
            with brain_entry.bind(other):
                with self.assertRaisesRegex(ValueError, "owner"):
                    brain_entry.run_step(self.ctx, self.STEP)
        handler.assert_not_called()

    def test_a_step_without_an_active_request_identity_is_refused(self):
        previous = getattr(self.ctx, "_cur_rid", None)
        self.ctx._cur_rid = ""
        self.addCleanup(setattr, self.ctx, "_cur_rid", previous)
        token = requests_state._current.set(None)
        self.addCleanup(requests_state._current.reset, token)
        with brain_entry.bind(self.outer):
            with self.assertRaisesRegex(ValueError, "etkin istek kimliği"):
                brain_entry.run_step(self.ctx, self.STEP)

    def test_real_multi_step_runner_gives_every_step_its_own_entry(self):
        seen = []

        def handler(command):
            seen.append((command, brain_entry.current()))
            return f"{command} bitti"

        def dispatch_spy(runtime, intent, args, command, lower):
            return handler(command)

        steps = ["sesi 30 yap", "notları aç"]
        with patch("modules.engine_intents.dispatch", side_effect=dispatch_spy), \
             patch("modules.brain_precedence.claim", return_value=None), \
             patch.object(self.ctx, "handle", side_effect=handler):
            with brain_entry.bind(self.outer):
                out = engine_sequence._run_steps(self.ctx, steps)
        self.assertEqual([text for text, _entry_row in seen], steps)
        for text, step_entry in seen:
            self.assertEqual(step_entry.text, text)
            self.assertEqual(step_entry.request_id, self.rid)
            self.assertIsNot(step_entry, self.outer)
        self.assertEqual(out.splitlines(), ["1. sesi 30 yap bitti", "2. notları aç bitti"])
        self.assertIs(self.ctx._session()._in_multi, False)


class AuthorityInvariantsTests(EngineFixture):
    """F + PR10a: korunan sınırlar ve PR10a sabitleri yerinde duruyor."""

    def test_core_guards_are_installed_once(self):
        brain_entry._install_core_guards(self.ctx)
        control = command_manager.engine_control
        brain_entry._install_core_guards(self.ctx)
        self.assertIs(command_manager.engine_control, control)
        self.assertFalse(getattr(command_manager, "_brain_engine_control_guard_installed", False))

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

    def test_classifier_has_no_production_call_site_left(self):
        self.assertEqual(_referencing(r"intent_router\.classify\(|import modules\.router|from modules import [^\n]*\brouter\b"), set())
        self.assertFalse((MODULES / "router.py").exists())


if __name__ == "__main__":
    unittest.main()
