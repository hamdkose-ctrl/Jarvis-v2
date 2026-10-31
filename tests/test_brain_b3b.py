"""PR7 Closeout-B3b: goal question via Brain relation, hint ownership, caller-zero guards."""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_core_map, brain_entry, brain_understanding, goal_executor
from modules.brain_contracts import ConversationRelation, RequestKind

MODULES = Path(__file__).resolve().parent.parent / "modules"


class GoalQuestionTests(unittest.TestCase):
    def handle(self, entry, text="x"):
        job = {"state": "question", "updated": 0}
        runtime = SimpleNamespace(profile=SimpleNamespace(slug="alice"))
        with patch.object(goal_executor, "latest", return_value=job), patch.object(goal_executor, "age", return_value=1), \
             patch.object(goal_executor, "run", return_value="RESUMED") as run, \
             patch.object(goal_executor, "_is_fast_command", return_value=False):
            if entry is None:
                with patch("modules.work_modes.ends_with_action", return_value=False) as legacy:
                    out = goal_executor.handle(runtime, text)
                    return out, run, legacy
            with brain_entry.bind(entry):
                with patch("modules.work_modes.ends_with_action", side_effect=AssertionError("work_modes çağrılmamalı")):
                    return goal_executor.handle(runtime, text), run, None

    def entry(self, kind, relation=ConversationRelation.NEW_REQUEST):
        semantic = fx.understanding(kind=kind, relation=relation)
        return fx.entry(brain_entry, semantic=semantic)

    def test_plain_answer_resumes_goal_without_work_modes(self):
        out, run, _ = self.handle(self.entry(RequestKind.CHAT))
        self.assertEqual(out, "RESUMED")
        run.assert_called_once()

    def test_new_capability_supersedes_question(self):
        out, run, _ = self.handle(self.entry(RequestKind.CAPABILITY))
        self.assertIsNone(out)
        run.assert_not_called()

    def test_topic_change_supersedes_question(self):
        out, run, _ = self.handle(self.entry(RequestKind.CHAT, ConversationRelation.TOPIC_CHANGE))
        self.assertIsNone(out)

    def test_without_entry_live_keeps_legacy_rule(self):
        out, run, legacy = self.handle(None)
        self.assertEqual(out, "RESUMED")
        legacy.assert_called_once()


class HintOwnershipTests(unittest.TestCase):
    def emitted_hints(self):
        source = (MODULES / "brain_understanding.py").read_text(encoding="utf-8")
        body = source[source.index("def _capability_hint"):source.index("_LEVEL_WORDS = {")]
        hints = set(re.findall(r'return (?:"([a-z.]+)"|"([a-z.]+)" if)', body))
        flat = {a or b for a, b in hints}
        flat |= set(re.findall(r'else "([a-z.]+)"', body))
        flat.add(brain_understanding.LEVEL_CAPABILITY)
        return flat

    def test_every_emitted_hint_has_a_core_intent_or_named_legacy_owner(self):
        hints = self.emitted_hints()
        self.assertTrue({"notes.read", "weather.read", "files.read", "reminder.propose", "research.search"} <= hints, hints)
        for hint in hints:
            self.assertIsNotNone(brain_core_map.hint_owner(hint), hint)

    def test_owners_do_not_overlap_core_intents(self):
        self.assertFalse(set(brain_core_map.CORE_INTENTS) & set(brain_core_map.LEGACY_OWNED_HINTS))


def _referencing(pattern):
    found = set()
    for path in MODULES.glob("*.py"):
        if re.search(pattern, path.read_text(encoding="utf-8")):
            found.add(path.name)
    return found


class CallerZeroGuards(unittest.TestCase):
    """Pins who may still reference each legacy authority. New callers fail; PR9 deletes the rest."""

    def test_brain_flow_never_projects_document_intents(self):
        source = (MODULES / "brain_entry.py").read_text(encoding="utf-8")
        body = source[source.index("def _legacy_route_projection"):source.index("def _install_route_guard")]
        intents = set(re.findall(r'"intent": "([a-z_]+)"', body))
        self.assertLessEqual(intents, {"clarify", "task", "chat"})
        self.assertFalse({i for i, _ in brain_core_map.CORE_INTENTS.values()} & {"doc_summary", "doc_insight", "doc_convert", "doc_translate"})

    def test_resolve_doc_is_only_reachable_from_intent_dispatch(self):
        self.assertEqual(_referencing(r"\._resolve_doc\("), {"engine_intents.py", "engine_tools.py"})  # engine_tools = thin wrapper

    def test_reference_context_only_feeds_legacy_router(self):
        self.assertEqual(_referencing(r"reference_context\("), {"app_actions.py", "router.py"})

    def test_work_modes_only_router_and_live_fallback(self):
        self.assertEqual(_referencing(r"work_modes"), {"router.py", "goal_executor.py", "freshness.py"})
        source = (MODULES / "goal_executor.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("work_modes"), 1)  # the Live-only fallback, behind brain_entry.goal_question_superseded()

    def test_router_classify_has_no_brain_flow_caller(self):
        self.assertEqual(_referencing(r"intent_router\.classify\("), {"engine_tools.py"})


if __name__ == "__main__":
    unittest.main()
