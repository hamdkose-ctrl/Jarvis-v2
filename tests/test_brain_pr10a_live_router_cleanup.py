"""PR10a RED: no dormant Live duplicate and no second (legacy router) semantic authority.

A  production Live binding is the canonical `engine_live_brain` implementation only.
B  a canonical Brain request never reaches `router.classify`.
C  the legacy router chain keeps zero new production callers (static lock).
D  canonical reference resolution never calls `app_actions.reference_context`.
E  the same semantic request reaches the same canonical Understanding/Core path from Text and Live.
F  `work_modes` is no longer a production semantic authority outside the legacy router chain.
"""
from __future__ import annotations

import ast
import contextlib
import functools
import importlib.util
import re
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_privacy_voice_and_pending  # noqa: F401  (shared stubs: pyautogui and friends)
import test_engine_modular as fixtures
from modules import (app_actions, brain_actions, brain_entry, engine_live_brain, engine_runtime,
                     engine_voice, goal_executor, session_state)

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"
OWNER = "hamdi"
RID = "req-pr10a-1"
LEGACY = {"router", "work_modes", "freshness"}


def production_files():
    files = sorted(MODULES.glob("*.py")) + sorted(ROOT.glob("*.py"))
    return [path for path in files if path.stem not in LEGACY]


def legacy_imports():
    """(file, legacy module, local alias) for every import form that reaches a legacy semantic module."""
    found = set()
    for path in production_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom):
                last = (node.module or "").split(".")[-1]
                for alias in node.names:
                    if last in LEGACY:
                        found.add((path.name, last, alias.asname or alias.name))
                    elif alias.name in LEGACY:
                        found.add((path.name, alias.name, alias.asname or alias.name))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    last = alias.name.split(".")[-1]
                    if last in LEGACY:
                        found.add((path.name, last, alias.asname or alias.name))
    return found


def referencing(pattern: str) -> set[str]:
    return {path.name for path in MODULES.glob("*.py") if re.search(pattern, path.read_text(encoding="utf-8"))}


class LiveBindingTests(unittest.TestCase):
    """A — one canonical Live implementation."""

    def context(self):
        return fixtures.ModularEngineTests.context(self)

    def test_live_command_is_exported_only_by_the_canonical_module(self):
        self.assertEqual(engine_runtime._HANDLERS["engine_live_brain"], ("_live_command",))
        self.assertNotIn("_live_command", engine_runtime._HANDLERS["engine_voice"])

    def test_runtime_live_binding_is_the_canonical_function(self):
        runtime = self.context()
        bound = runtime._live_command.__wrapped__          # engine_voice._pc_context sarımı
        self.assertIsInstance(bound, functools.partial)
        self.assertIs(bound.func, engine_live_brain._live_command)
        self.assertIs(bound.args[0], runtime)

    def test_dormant_live_duplicate_is_physically_gone(self):
        self.assertFalse(hasattr(engine_voice, "_live_command"))

    def test_engine_voice_keeps_its_real_voice_helpers(self):
        for name in ("_sounds_like_wake", "find_wake", "_strip_wake",
                     "_pc_context", "list_input_devices"):
            self.assertTrue(hasattr(engine_voice, name), name)

    def test_engine_voice_holds_no_retired_live_session_helpers(self):
        # Canlı oturum talimatı, sözlüğü, açılma olayı ve araç çiti Gemini Live'la birlikte
        # emekli oldu (§9). Bu modül onlardan yalnız yaşayan yüzeyleri tutar.
        for name in ("_live_prompt", "_live_vocab", "live_session_opened", "prepare_live_tool"):
            self.assertFalse(hasattr(engine_voice, name), name)

    def test_engine_voice_no_longer_holds_a_second_command_entry(self):
        tree = ast.parse((MODULES / "engine_voice.py").read_text(encoding="utf-8"))
        names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("_live_command", names)
        handle_calls = [node for node in ast.walk(tree)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "handle"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "runtime"]
        self.assertEqual(handle_calls, [])


class CanonicalRequestTests(unittest.TestCase):
    """B, D, E — real prepare/handoff, no synthetic UnderstandingResult."""

    def setUp(self):
        self.store = session_state.SessionStore()
        self.state = self.store.for_owner(OWNER)
        self.real_build_context = brain_entry.brain_context.build_active_context
        self.runtime = SimpleNamespace(
            profile=SimpleNamespace(slug=OWNER, name="Hamdi", data={}),
            _sessions=self.store, _session=lambda: self.state,
            flags={"sleep": False}, _pending_photo={},
        )

    def context(self, **kwargs):
        kwargs.setdefault("history_reader", lambda owner, *, limit: [])
        kwargs.setdefault("history_filter", lambda owner, rows: rows)
        kwargs.setdefault("goal_reader", lambda owner: None)
        kwargs.setdefault("goal_is_open", lambda row: False)
        return self.real_build_context(**kwargs)

    def guards(self, stack):
        from dataclasses import replace
        from modules.brain_contracts import RequestKind
        def model(current, text, *, active_context=None):
            return replace(current, request_kind=RequestKind.CAPABILITY,
                           capability_hint='weather.read', arguments={'location': 'ankara'})
        stack.enter_context(patch.object(brain_entry, 'apply_model_understanding', side_effect=model))
        for target in (patch.object(brain_entry.brain_context, "build_active_context",
                                    lambda **kwargs: self.context(**kwargs)),
                       patch("modules.job_front.observe", lambda owner: None),
                       patch("modules.desktop_agent._load", lambda owner: None),
                       patch.object(brain_entry, "_install_core_guards"),
                       patch.object(brain_entry, "_correlated_job_id", return_value=None)):
            stack.enter_context(target)

    def text_turn(self, text: str, handler):
        with contextlib.ExitStack() as stack:
            self.guards(stack)
            dispatch = stack.enter_context(patch("modules.engine_intents.dispatch", return_value="<<core>>"))
            entry = brain_entry.prepare(self.runtime, owner=OWNER, request_id=RID, text=text, source="yazı", model_understanding=True)
            output, _feedback, _job = brain_entry.handoff(self.runtime, entry, handler, text)
        return entry, output, dispatch

    def live_turn(self, text: str, handler):
        runtime = self.runtime
        runtime.slugify = lambda name: str(name).casefold()
        runtime.pc_profile = lambda: SimpleNamespace(name="Hamdi", slug=OWNER)
        runtime.secrets = SimpleNamespace(token_hex=lambda n: RID)
        runtime.requests_state = SimpleNamespace(
            register=Mock(return_value=True), activate=lambda *a, **kw: nullcontext(), check=lambda: None,
            cancel=lambda *a: None, Cancelled=RuntimeError)
        runtime.log = Mock()
        runtime.emit = Mock()
        runtime.handle = handler
        runtime._record_failure = Mock()
        runtime._finalize = lambda out: out
        runtime._tr_lower = lambda text: text.lower()
        runtime.agents = SimpleNamespace(classify=lambda text: "chat")
        runtime._cur_source = runtime._cur_rid = ""
        with contextlib.ExitStack() as stack:
            self.guards(stack)
            dispatch = stack.enter_context(patch("modules.engine_intents.dispatch", return_value="<<core>>"))
            output = engine_live_brain._live_command(runtime, text)
        return output, dispatch

    def test_text_and_live_reach_the_same_canonical_core_dispatch(self):
        text = "ankara'da hava nasıl"
        entry, text_out, text_dispatch = self.text_turn(text, Mock(return_value="<<handler>>"))
        live_out, live_dispatch = self.live_turn(text, Mock(return_value="<<handler>>"))

        self.assertEqual(entry.understanding.capability_hint, "weather.read")
        self.assertEqual(text_dispatch.call_args.args[1:3], live_dispatch.call_args.args[1:3])
        self.assertEqual((text_dispatch.call_args.args[1], text_dispatch.call_args.args[2]),
                         ("weather", {"location": "Ankara"}))
        self.assertEqual(text_out, live_out)

    def test_live_and_text_never_call_the_legacy_classifier(self):
        # Emekli classifier'ın yerinde ikinci bir yetki yok; çağrı kapısı fiziksel olarak kalktı.
        self.assertIsNone(importlib.util.find_spec("modules.router"))
        for text in ("ankara'da hava nasıl", "sesi 50 yap", "merhaba"):
            with self.subTest(text=text):
                self.text_turn(text, Mock(return_value="<<handler>>"))
                self.live_turn(text, Mock(return_value="<<handler>>"))

    def test_canonical_reference_resolution_never_calls_legacy_reference_context(self):
        self.assertFalse(hasattr(app_actions, "reference_context"))
        entry, _output, _dispatch = self.text_turn("bunu özetle", Mock(return_value="<<handler>>"))
        self.assertEqual(entry.stage, "understanding")

    def test_live_path_still_uses_the_owner_request_fence(self):
        handler = Mock(return_value="<<handler>>")
        with patch.object(brain_entry, "prepare", wraps=brain_entry.prepare) as prepare:
            self.live_turn("sesi 50 yap", handler)
        self.assertEqual(prepare.call_args.kwargs["source"], "ses")
        self.assertEqual(prepare.call_args.kwargs["owner"], OWNER)
        self.assertEqual(prepare.call_args.kwargs["request_id"], RID)


class CallerZeroGuardTests(unittest.TestCase):
    """C, F — PR10c: legacy semantic zinciri artık production'da değildir; yeni çağıran da eklenemez."""

    def test_legacy_semantic_modules_have_no_production_importer(self):
        self.assertEqual(legacy_imports(), set())

    def test_legacy_semantic_modules_are_physically_gone(self):
        for name in sorted(LEGACY):
            self.assertFalse((MODULES / f"{name}.py").exists(), name)
            self.assertIsNone(importlib.util.find_spec("modules." + name), name)

    def test_classifier_has_no_production_call_site(self):
        self.assertEqual(referencing(r"intent_router\.classify\("), set())

    def test_reference_context_has_no_producer_or_caller(self):
        self.assertEqual(referencing(r"reference_context\("), set())

    def test_goal_executor_falls_back_to_the_brain_action_definition(self):
        job = {"state": "question", "updated": 0}
        state = SimpleNamespace(_in_multi=False, _in_macro=False)
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER), _session=lambda: state)
        with patch.object(goal_executor, "latest", return_value=job), \
             patch.object(goal_executor, "age", return_value=1), \
             patch.object(goal_executor, "_is_fast_command", return_value=False), \
             patch.object(brain_actions, "ends_with_action", wraps=brain_actions.ends_with_action) as rule, \
             patch.object(goal_executor, "run", return_value="RESUMED") as run:
            output = goal_executor.handle(runtime, "raporu dosyaya yaz")
        self.assertIsNone(output)
        run.assert_not_called()
        # Bağlı canonical entry yok; yedek kural tek tanımdan (brain_actions) gelir.
        self.assertTrue(rule.called)

    def test_ends_with_action_has_a_single_definition(self):
        self.assertEqual(referencing(r"def ends_with_action"), {"brain_actions.py"})


if __name__ == "__main__":
    unittest.main()
