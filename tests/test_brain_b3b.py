"""PR7 Closeout-B3b: goal question via Brain relation, hint ownership, caller-zero guards."""
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_actions, brain_core_map, brain_entry, brain_understanding, goal_executor, work_modes
from modules.brain_contracts import ConversationRelation, RequestKind

MODULES = Path(__file__).resolve().parent.parent / "modules"


OLD_NEW_SENTENCES = [
    "devam et", "raporu dosyaya yaz", "masaüstünü düzenle", "kaydet", "bunu araştır", "bunu yap", "bir uygulama yaz",
    "evet", "tübitak kaynaklarını kullan", "yapay zeka nedir", "yazın tatile nereye gidelim", "bunu nasıl yaparım",
    "yarın hava nasıl olacak", "bana hatırlat", "belgeyi özetle", "ankara'da hava nasıl", "sesi 50 yap",
    "kırmızı olsun", "hayır", "mavi", "excel olarak kaydet", "pdf'e çevir", "dosyayı sil", "chrome'u aç",
    "notlarımı oku", "hepsi", "ikincisi", "tamam", "olur", "2", "bugün ne yapıyoruz", "kaynakları listele",
    "raporu gönder", "e-postayı gönderir misin", "bunu kapat", "hava durumunu söyle", "rapor.pdf'i oku",
    "evet devam et", "hayır iptal", "python ile yaz",
]
# Intentional improvements: Understanding sees a new capability the old verb rule could not.
IMPROVED = {"yarın hava nasıl olacak", "bana hatırlat", "belgeyi özetle", "ankara'da hava nasıl", "notlarımı oku"}


def real_entry(text):
    semantic = brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text,
                                              active_context=fx.context(), candidates=(), references=())
    return fx.entry(brain_entry, semantic=semantic)


def superseded(text, runtime=None):
    with brain_entry.bind(real_entry(text)):
        return brain_entry.goal_question_superseded(runtime)


class GoalQuestionTests(unittest.TestCase):
    """Real Understanding, no synthetic UnderstandingResult."""

    def test_old_vs_new_table_has_no_regression_and_only_the_listed_improvements(self):
        self.assertEqual(len(OLD_NEW_SENTENCES), 40)
        regressions, improvements = [], set()
        for text in OLD_NEW_SENTENCES:
            old, new = work_modes.ends_with_action(text), superseded(text)
            if old and not new:
                regressions.append(text)
            if new and not old:
                improvements.add(text)
        self.assertEqual(regressions, [])
        self.assertEqual(improvements, IMPROVED)

    def test_action_rule_is_one_definition_owned_by_brain(self):
        self.assertIs(work_modes.ends_with_action, brain_actions.ends_with_action)
        for text in ("raporu dosyaya yaz", "masaüstünü düzenle", "kaydet", "bunu araştır", "bunu yap", "bir uygulama yaz"):
            self.assertIn(brain_understanding.ACTION_REQUEST_CODE, real_entry(text).understanding.reason_codes, text)

    def handle(self, text, runtime_flags=None):
        job = {"state": "question", "updated": 0}
        state = SimpleNamespace(_in_multi=False, _in_macro=False, **(runtime_flags or {}))
        runtime = SimpleNamespace(profile=SimpleNamespace(slug="alice"), _session=lambda: state)
        with patch.object(goal_executor, "latest", return_value=job), patch.object(goal_executor, "age", return_value=1), \
             patch.object(goal_executor, "run", return_value="RESUMED") as run, \
             patch.object(goal_executor, "_is_fast_command", return_value=False):
            with brain_entry.bind(real_entry(text)):
                with patch("modules.work_modes.ends_with_action", side_effect=AssertionError("work_modes çağrılmamalı")):
                    return goal_executor.handle(runtime, text), run

    def test_goal_question_scenarios_through_goal_executor(self):
        for text in ("kırmızı olsun", "evet", "tübitak kaynaklarını kullan", "bunu nasıl yaparım"):
            with self.subTest(answer=text):
                out, run = self.handle(text)
                self.assertEqual(out, "RESUMED")
        for text in ("raporu dosyaya yaz", "masaüstünü düzenle", "kaydet", "bunu araştır", "bunu yap",
                     "bir uygulama yaz", "yarın hava nasıl olacak"):
            with self.subTest(new_request=text):
                out, run = self.handle(text)
                self.assertIsNone(out)
                run.assert_not_called()

    def test_nested_step_falls_back_to_legacy_rule_not_the_whole_utterance_entry(self):
        for flag in ("_in_multi", "_in_macro"):
            state = SimpleNamespace(_in_multi=False, _in_macro=False)
            setattr(state, flag, True)
            runtime = SimpleNamespace(_session=lambda s=state: s)
            self.assertIsNone(superseded("raporu dosyaya yaz", runtime))

    def test_without_entry_live_keeps_legacy_rule(self):
        self.assertIsNone(brain_entry.goal_question_superseded())


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
            if hint in brain_core_map.PARTIAL_CORE_HINTS:
                self.assertIn(hint, brain_core_map.CORE_INTENTS)

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
        # B3c-1: the only document intent Core may plan is doc_summary, from a validated resolved path.
        self.assertEqual({i for i, _ in brain_core_map.CORE_INTENTS.values()} & {"doc_summary", "doc_insight", "doc_convert", "doc_translate"},
                         {"doc_summary"})

    def test_resolve_doc_is_only_reachable_from_intent_dispatch(self):
        self.assertEqual(_referencing(r"\._resolve_doc\("), {"engine_intents.py", "engine_tools.py"})  # engine_tools = thin wrapper

    def test_reference_context_only_feeds_legacy_router(self):
        self.assertEqual(_referencing(r"reference_context\("), {"app_actions.py", "router.py"})

    def test_work_modes_only_router_and_live_fallback(self):
        self.assertEqual(_referencing(r"work_modes"), {"router.py", "goal_executor.py", "freshness.py", "brain_actions.py"})
        source = (MODULES / "goal_executor.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("work_modes"), 1)  # the Live-only fallback, behind brain_entry.goal_question_superseded()

    def test_router_classify_has_no_brain_flow_caller(self):
        self.assertEqual(_referencing(r"intent_router\.classify\("), {"engine_tools.py"})


if __name__ == "__main__":
    unittest.main()
