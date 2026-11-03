"""PR7 Closeout-B3b: goal question via Brain relation, hint ownership, caller-zero guards."""
import importlib.util
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_actions, brain_core_map, brain_entry, brain_understanding, goal_executor
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
# "hava durumunu söyle" is one of the legacy-owned weather status commands; the canonical
# capability decision now recognizes it as an independent new request (no pending owner).
IMPROVED = {"yarın hava nasıl olacak", "bana hatırlat", "belgeyi özetle", "ankara'da hava nasıl", "notlarımı oku",
            "hava durumunu söyle"}


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
            old, new = brain_actions.ends_with_action(text), superseded(text)
            if old and not new:
                regressions.append(text)
            if new and not old:
                improvements.add(text)
        self.assertEqual(regressions, [])
        self.assertEqual(improvements, IMPROVED)

    def test_action_rule_is_one_definition_owned_by_brain(self):
        # Eski fiil kuralı tek tanımda yaşıyor: brain_actions. İkinci bir tanım veya re-export yok.
        self.assertEqual(_referencing(r"def ends_with_action"), {"brain_actions.py"})
        self.assertEqual(_referencing(r"\bwork_modes\b"), set())
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
                # Bağlı canonical entry varken goal_executor yedek fiil kuralına düşmez; düşünce bu kapı patlar.
                with patch.object(brain_actions, "ends_with_action",
                                  side_effect=AssertionError("bağlı Brain girişi varken yedek fiil kuralı çağrılamaz")):
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
    """PR10c: emeklilik fizikseldir. Silinen ikinci yetki yolları geri gelemez; yeni bir çağıran
    bu kilitleri anında kırar."""

    RETIRED_AUTHORITY_SOURCES = ("router.py", "work_modes.py", "freshness.py", "chat_translation.py")
    RETIRED_AUTHORITY_NAMES = ("router", "work_modes", "freshness", "chat_translation")

    def test_brain_flow_never_projects_document_intents(self):
        source = (MODULES / "brain_entry.py").read_text(encoding="utf-8")
        body = source[source.index("def _legacy_route_projection"):source.index("def nested_step")]
        intents = set(re.findall(r'"intent": "([a-z_]+)"', body))
        self.assertLessEqual(intents, {"clarify", "task", "chat"})
        # Final file cutover: normal Brain file operations use one Core file_action; old doc_* are gone.
        intents = {i for i, _ in brain_core_map.CORE_INTENTS.values()}
        self.assertIn("file_action", intents)
        self.assertFalse(intents & {"doc_summary", "doc_insight", "doc_convert", "doc_translate"})

    def test_retired_authority_files_are_physically_removed(self):
        for name in self.RETIRED_AUTHORITY_SOURCES:
            self.assertFalse((MODULES / name).exists(), name)
        for module in self.RETIRED_AUTHORITY_NAMES:
            self.assertIsNone(importlib.util.find_spec("modules." + module), module)

    def test_no_production_source_references_a_retired_authority(self):
        pattern = (r"import (?:modules\.)?(?:router|work_modes|freshness|chat_translation)\b|"
                   r"\bintent_router\.classify\(|\brouter\.classify\(|reference_context\(|_resolve_doc\(")
        self.assertEqual(_referencing(pattern), set())

    def test_doc_intents_have_no_producer_anywhere(self):
        self.assertEqual(_referencing(r'"doc_(?:summary|insight|convert|translate)"'), set())

    def test_legacy_classifier_call_sites_are_gone(self):
        self.assertEqual(_referencing(r"intent_router\.classify\(|router\.classify\("), set())


if __name__ == "__main__":
    unittest.main()
