"""PR7 Closeout-B1: Core-validated capability hint, level request understanding, pre-queue fast lane."""
import ast
import queue
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import test_privacy_voice_and_pending
if 'pyautogui' not in sys.modules:
    _keyboard = ModuleType('pyautogui')
    _keyboard.__getattr__ = lambda name: Mock()
    sys.modules['pyautogui'] = _keyboard

from modules import brain_core_map, brain_entry, engine_intents, engine_queue, session_state
from modules.brain_contracts import ActiveContext, ContextReference, ConversationRelation, RequestKind
from modules.brain_understanding import LEVEL_CAPABILITY, LEVEL_UNSPECIFIED, understand
import test_brain_production_entry as fixtures

OWNER = fixtures.OWNER
RID = fixtures.RID
ROOT = Path(__file__).resolve().parents[1]


def with_property(value):
    refs = ()
    if value:
        refs = (ContextReference(owner=OWNER, id="last_property", kind="conversation_state", source="session_state",
                                 provenance={"field": "last_property", "value": value}),)
    return ActiveContext(owner=OWNER, request_id=RID, recent_references=refs)


def understood(text, prop=None):
    return understand(owner=OWNER, request_id=RID, text=text, active_context=with_property(prop),
                      candidates=(), references=())


class LevelUnderstandingTests(unittest.TestCase):
    def test_explicit_property_needs_no_context(self):
        for text, prop, level in [("sesi 50 yap", "volume", 50), ("ses seviyesini 20 yap", "volume", 20),
                                  ("parlaklığı 30 yap", "brightness", 30), ("ekran parlaklığı 80", "brightness", 80),
                                  ("sesi yüzde 40 yap", "volume", 40), ("parlaklığı 250 yap", "brightness", 100)]:
            result = understood(text)
            self.assertEqual(result.request_kind, RequestKind.CAPABILITY, text)
            self.assertEqual(result.capability_hint, LEVEL_CAPABILITY, text)
            self.assertEqual((result.arguments["property"], result.arguments["level"]), (prop, level), text)

    def test_bare_number_uses_fresh_last_property(self):
        for prop in ("volume", "brightness"):
            for text in ("70 yap", "yüzde 70 yap", "yüzde 70"):
                result = understood(text, prop)
                self.assertEqual(result.capability_hint, LEVEL_CAPABILITY, text)
                self.assertEqual((result.arguments["property"], result.arguments["level"]), (prop, 70))

    def test_bare_number_without_property_asks(self):
        for prop in (None, "sicaklik"):
            result = understood("70 yap", prop)
            self.assertEqual(result.request_kind, RequestKind.CLARIFY)
            self.assertTrue(result.needs_input)
            self.assertIn(LEVEL_UNSPECIFIED, result.ambiguities)
            self.assertIsNone(result.capability_hint)
            self.assertEqual(result.arguments["level"], 70)

    def test_plain_number_and_other_text_are_not_level_requests(self):
        for text in ("70", "ses nedir", "sesi aç", "70 kişi geldi", "başka konu", "boşver, 70 yap"):
            result = understood(text, "volume")
            self.assertNotEqual(result.capability_hint, LEVEL_CAPABILITY, text)
            self.assertNotIn(LEVEL_UNSPECIFIED, result.ambiguities, text)


class CoreMapTests(unittest.TestCase):
    def test_only_listed_hints_validated_and_clamped(self):
        self.assertEqual(brain_core_map.core_plan(LEVEL_CAPABILITY, {"property": "volume", "level": 70}),
                         ("level_set", {"property": "volume", "level": 70}))
        self.assertEqual(brain_core_map.core_plan(LEVEL_CAPABILITY, {"property": "volume", "level": 500})[1]["level"], 100)
        self.assertEqual(brain_core_map.core_plan(LEVEL_CAPABILITY, {"property": "brightness", "level": -4})[1]["level"], 0)

    def test_invalid_input_never_becomes_a_plan(self):
        for args in ({}, {"property": "banana", "level": 5}, {"property": "volume", "level": "70"},
                     {"property": "volume", "level": True}, {"level": 5}):
            self.assertIsNone(brain_core_map.core_plan(LEVEL_CAPABILITY, args), args)
        for hint in (None, "", "notes.read", "files.read", "reminder.propose", "research.search", "shutdown", "pc.level.set.x"):
            self.assertIsNone(brain_core_map.core_plan(hint, {"property": "volume", "level": 5}), hint)

    def test_proposal_stays_free_of_authority(self):
        entry = fixtures.entry(brain_entry, semantic=understood("sesi 50 yap"))
        self.assertFalse(fixtures._RESERVED.intersection(brain_entry.core_proposal(entry)))


class HandoffTests(unittest.TestCase):
    def runtime(self):
        state = session_state.SessionState()
        return SimpleNamespace(profile=SimpleNamespace(slug=OWNER, name="Hamdi", data={}), _sessions=object(),
                               _session=lambda: state), state

    def entry(self, text, prop=None, active=None):
        semantic = understood(text, prop)
        entry = fixtures.entry(brain_entry, semantic=semantic, active=active or with_property(prop))
        return entry

    def handoff(self, entry, runtime, handler=None):
        handler = handler or Mock(side_effect=AssertionError("ham metin eski handler'a gitmemeli"))
        with patch.object(brain_entry, "_install_core_guards"), patch.object(brain_entry, "_correlated_job_id", return_value=None):
            return brain_entry.handoff(runtime, entry, handler, "komut")

    def test_mapped_hint_dispatches_validated_core_intent_not_raw_text(self):
        runtime, _ = self.runtime()
        with patch("modules.engine_intents.dispatch", return_value="Ses seviyesini yüzde 70 yaptım.") as dispatch:
            output, feedback, _ = self.handoff(self.entry("70 yap", "volume"), runtime)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1:3], ("level_set", {"property": "volume", "level": 70}))
        self.assertEqual((feedback.result_status, feedback.reason_code), ("handled", "CORE_HANDOFF_RETURNED"))

    def test_bare_number_without_property_asks_and_core_opens_pending_level(self):
        runtime, state = self.runtime()
        handler = Mock(side_effect=AssertionError("handler çağrılmamalı"))
        output, feedback, _ = self.handoff(self.entry("70 yap", None), runtime, handler)
        self.assertEqual(output, "Yüzde 70, ses mi parlaklık mı?")
        self.assertEqual(state.pending_level, 70)
        self.assertEqual(feedback.result_status, "needs_input")

    def test_unrelated_open_pending_state_does_not_veto_a_validated_plan(self):
        runtime, _ = self.runtime()
        pending = ContextReference(owner=OWNER, id="pending_confirm", kind="pending_state", source="session_state",
                                   provenance={"field": "pending_confirm"})
        active = ActiveContext(owner=OWNER, request_id=RID, pending_references=(pending,))
        entry = self.entry("sesi 50 yap", active=active)
        # Slot varlığı relation authority değildir: NEW_REQUEST + CAPABILITY planı çalışır.
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertEqual(brain_entry.core_plan(entry), ("level_set", {"property": "volume", "level": 50}))

    def test_state_or_fast_match_never_plans(self):
        from modules.brain_gates import GateObservation
        semantic = understood("sesi 50 yap")
        fast = GateObservation(OWNER, RID, "fast", True, "EXACT", protocol="fast.time.read", selection="time")
        entry = fixtures.entry(brain_entry, semantic=semantic, fast=fast)
        self.assertIsNone(brain_entry.core_plan(entry))

    def test_route_projection_mirrors_plan(self):
        entry = self.entry("sesi 50 yap")
        self.assertEqual(brain_entry._legacy_route_projection(entry), {"intent": "level_set", "args": {"property": "volume", "level": 50}})


class LevelSetIntentTests(unittest.TestCase):
    def runtime(self, volume_ok=True, bright_ok=True):
        state = session_state.SessionState()
        control = Mock(set_volume=Mock(return_value=volume_ok), set_brightness_verified=Mock(return_value=bright_ok))
        return SimpleNamespace(_session=lambda: state, system_control=control), state

    def run_intent(self, runtime, args):
        with patch("modules.requests_state.check"):
            return engine_intents.dispatch(runtime, "level_set", args, "x", "x")

    def test_volume_success_remembers_property(self):
        runtime, state = self.runtime()
        self.assertEqual(self.run_intent(runtime, {"property": "volume", "level": 70}), "Ses seviyesini yüzde 70 yaptım.")
        runtime.system_control.set_volume.assert_called_once_with(70)
        self.assertEqual(session_state.fresh_property(state), "volume")

    def test_brightness_success_remembers_property(self):
        runtime, state = self.runtime()
        self.assertIn("parlaklığını yüzde 30", self.run_intent(runtime, {"property": "brightness", "level": 30}))
        self.assertEqual(session_state.fresh_property(state), "brightness")

    def test_failures_are_reported_and_not_remembered(self):
        runtime, state = self.runtime(volume_ok=False, bright_ok=False)
        self.assertIn("ayarlayamadım", self.run_intent(runtime, {"property": "volume", "level": 70}))
        self.assertIn("doğrulayamadım", self.run_intent(runtime, {"property": "brightness", "level": 70}))
        self.assertIsNone(session_state.fresh_property(state))


class FastLaneTests(unittest.TestCase):
    def test_only_queue_safe_protocol_matches(self):
        hit = brain_entry.fast_lane(OWNER, RID, "hedef durumu")
        self.assertEqual((hit.protocol, hit.selection), ("fast.goal.status", "summary"))
        self.assertEqual(brain_entry.fast_lane(OWNER, RID, "hedef ayrıntıları").selection, "details")
        for text in ("saat kaç", "jarvis kapat", "uyu", "merhaba", "hedef durumu nedir acaba"):
            self.assertIsNone(brain_entry.fast_lane(OWNER, RID, text), text)

    def test_submit_answers_status_without_enqueue_and_enqueues_the_rest(self):
        profile = SimpleNamespace(name="Alice", slug="alice")
        rt = SimpleNamespace(_tr_lower=str.casefold, slugify=lambda value: "alice", pc_profile=lambda: profile,
                             _get_profile=Mock(return_value=profile), _emit_for=Mock(), events=queue.Queue(),
                             requests_state=SimpleNamespace(register=Mock(return_value=True), activate=lambda *a: nullcontext()),
                             voice=Mock(), secrets=SimpleNamespace(token_hex=lambda n: "rid"))
        with patch("modules.goal_executor.latest", return_value=None):
            self.assertTrue(engine_queue.submit(rt, "hedef durumu", user="Alice", rid="r1"))
        self.assertTrue(rt.events.empty())
        rt._emit_for.assert_any_call(profile, "assistant", "Kayıtlı hedef yok.", "yazı", rid="r1")
        self.assertTrue(engine_queue.submit(rt, "saat kaç", user="Alice", rid="r2"))
        self.assertEqual(rt.events.get_nowait()[1], "saat kaç")

    def test_broken_fast_lane_never_loses_the_command(self):
        profile = SimpleNamespace(name="Alice", slug="alice")
        rt = SimpleNamespace(_tr_lower=str.casefold, slugify=lambda value: "alice", pc_profile=lambda: profile,
                             _get_profile=Mock(return_value=profile), _emit_for=Mock(), events=queue.Queue(),
                             requests_state=SimpleNamespace(register=Mock(return_value=True), activate=lambda *a: nullcontext()),
                             voice=Mock(), secrets=SimpleNamespace(token_hex=lambda n: "rid"), _record_failure=Mock())
        with patch.object(brain_entry, "fast_lane", side_effect=RuntimeError("bozuk")):
            self.assertTrue(engine_queue.submit(rt, "hedef durumu", user="Alice", rid="r9"))
        self.assertEqual(rt.events.get_nowait()[1], "hedef durumu")
        rt._record_failure.assert_called_once_with('modules/engine_queue.py:fast_lane')

    def test_queue_has_no_phrase_list_of_its_own(self):
        source = (ROOT / "modules" / "engine_queue.py").read_text(encoding="utf-8")
        self.assertNotIn("hedef durumu", source)


class RouterAuthorityTests(unittest.TestCase):
    LEGACY = {"router", "work_modes", "freshness"}

    def production_files(self):
        files = sorted((ROOT / "modules").glob("*.py")) + sorted(ROOT.glob("*.py"))
        return [path for path in files if path.stem not in self.LEGACY]

    def legacy_imports(self):
        """(file, legacy module, local alias) for every import form that reaches a legacy module."""
        found = set()
        for path in self.production_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.ImportFrom):
                    last = (node.module or "").split(".")[-1]
                    for alias in node.names:
                        if last in self.LEGACY:                      # from modules.router import classify [as x]
                            found.add((path.name, last, alias.asname or alias.name))
                        elif alias.name in self.LEGACY:              # from modules import router [as x]
                            found.add((path.name, alias.name, alias.asname or alias.name))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        last = alias.name.split(".")[-1]
                        if last in self.LEGACY:                      # import modules.router [as x]
                            found.add((path.name, last, alias.asname or alias.name))
        return found

    def test_legacy_modules_have_no_production_importer(self):
        self.assertEqual(self.legacy_imports(), set())

    def test_legacy_module_files_are_physically_gone(self):
        for name in sorted(self.LEGACY):
            self.assertFalse((ROOT / "modules" / f"{name}.py").exists(), name)

    def test_freshness_is_imported_by_nobody(self):
        self.assertFalse([row for row in self.legacy_imports() if row[1] == "freshness"])

    def test_no_production_source_calls_a_classifier_alias(self):
        aliases = {(name, alias) for name, module, alias in self.legacy_imports() if module == "router"}
        callers = []
        for path in self.production_files():
            local = {alias for name, alias in aliases if name == path.name} | {"router", "intent_router"}
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "classify":
                    base = func.value
                    name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                    if name in local:
                        callers.append(f"{path.name}:{name}")
                elif isinstance(func, ast.Name) and func.id in local and func.id not in {"router", "intent_router"}:
                    callers.append(f"{path.name}:{func.id}")      # from-import alias of classify
        self.assertEqual(callers, [])

    def test_brain_entered_request_never_reaches_the_legacy_classifier(self):
        # Sınıflandırılmış istek kapısı runtime'e bağlı bir yol değil: tek kapı brain_entry.route_command
        # ve o kapı yalnız bağlı turn'ün kendi kararını izdüşürür.
        legacy = Mock(side_effect=AssertionError("router.classify çağrılmamalı"))
        runtime = SimpleNamespace(route=legacy, intent_router=legacy, handle=lambda text: "CORE:" + text)
        for text in ("70 yap", "sesi 50 yap", "merhaba"):
            with brain_entry.bind(fixtures.entry(brain_entry, semantic=understood(text, "volume"))):
                self.assertIn(brain_entry.route_command(runtime, text)["intent"], {"chat", "clarify", "task"})
        legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
