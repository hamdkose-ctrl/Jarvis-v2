"""PR10c final cutover sözleşmeleri: production'da ikinci semantic authority kalmaz.

Katmanlar: (1) caller-zero/statik authority, (2) router retirement, (3) file target authority,
(4) Live context parity/read-only, (5) Live tool authority, (6) command_manager bounded gate.
Her test ya bir modülün fiziksilğini ya da davranışsal bir fail-closed sınırını ölçer; hiçbir
test legacy zinciri authority olarak kabul etmez. Yorum satırı/docstring taraması yapılmaz:
statik kontroller AST üzerinden gerçek kimliklere (import, isim, nitelik, intent sabiti) bakar.
"""
import ast
import importlib.util
import inspect
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"

# Göçü tamamlanan semantic sahiplikler: bunların production kaynağı yoktur.
RETIRED_MODULES = frozenset({"router", "work_modes", "freshness"})
RETIRED_IDENTIFIERS = frozenset({"reference_context", "catalog_prompt", "_resolve_doc",
                                 "doc_summary", "doc_insight", "doc_convert", "doc_translate"})


def source(name: str) -> str:
    return (MODULES / f"{name}.py").read_text(encoding="utf-8")


def identities(text: str):
    """Gerçek semantic başvuru kimlikleri: import edilen modüller, isimler, nitelikler, intent sabitleri."""
    found = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
            found |= {alias.asname for alias in node.names if alias.asname}
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[-1])
            found |= {alias.name for alias in node.names}
        elif isinstance(node, (ast.Name, ast.Attribute)):
            found.add(node.id if isinstance(node, ast.Name) else node.attr)
        elif isinstance(node, ast.FunctionDef):
            found.add(node.name)
        elif isinstance(node, ast.MatchValue) and isinstance(node.pattern.value, ast.Constant):
            if isinstance(node.pattern.value.value, str):
                found.add(node.pattern.value.value)
    return found - {None}


def production_identities():
    for path in sorted(MODULES.glob("*.py")):
        yield path.name, identities(path.read_text(encoding="utf-8"))


class RetiredModuleTests(unittest.TestCase):
    """Legacy router zinciri ikamet etmez: dosyalar fiziksel olarak kaldırılmış olmalı."""

    def test_retired_semantic_modules_are_physically_gone(self):
        for name in RETIRED_MODULES:
            self.assertIsNone(importlib.util.find_spec(f"modules.{name}"), f"modules/{name}.py hâlâ duruyor")
            self.assertFalse((MODULES / f"{name}.py").exists(), f"modules/{name}.py silinmemiş")

    def test_no_production_source_references_the_retired_authorities(self):
        offenders = []
        for filename, used in production_identities():
            offenders += [f"{filename}:{name}" for name in sorted(used & (RETIRED_MODULES | RETIRED_IDENTIFIERS))]
        self.assertEqual(offenders, [])

    def test_engine_facade_does_not_export_the_legacy_classifier(self):
        from modules import engine_runtime
        self.assertNotIn("intent_router", engine_runtime._DEPENDENCIES)
        self.assertNotIn("route", engine_runtime._HANDLERS["engine_tools"])
        self.assertNotIn("_resolve_doc", engine_runtime._HANDLERS["engine_tools"])
        context = engine_runtime.EngineContext()
        for name in ("intent_router", "route", "_resolve_doc", "_context_prompt"):
            self.assertFalse(hasattr(context, name), name)


class CanonicalRouteAuthorityTests(unittest.TestCase):
    """`runtime.route` tek kaynaktan beslenir: bağlı canonical Brain entry'nin izdüşümü."""

    def install(self, runtime):
        from modules import brain_entry
        brain_entry._install_route_guard(runtime)
        return runtime

    def test_guard_keeps_no_legacy_authority_reference(self):
        runtime = self.install(SimpleNamespace(route=lambda command: {"intent": "chat", "args": {}},
                                               _brain_route_guard_installed=False))
        self.assertFalse(hasattr(runtime, "_brain_legacy_route"))
        self.assertTrue(runtime._brain_route_guard_installed)

    def test_route_without_a_bound_entry_fails_closed(self):
        from modules import brain_entry
        runtime = self.install(SimpleNamespace(route=lambda command: self.fail("legacy route çağrıldı"),
                                               _brain_route_guard_installed=False))
        self.assertIsNone(brain_entry.current())
        decision = runtime.route("raporu özetle")
        self.assertEqual(decision["intent"], "clarify")
        self.assertIn("işlem başlatılmadı", decision["args"]["question"])

    def test_the_guard_is_idempotent(self):
        runtime = self.install(SimpleNamespace(route=lambda command: {}, _brain_route_guard_installed=False))
        guarded = runtime.route
        self.install(runtime)
        self.assertIs(runtime.route, guarded)

    def test_install_route_guard_takes_only_the_runtime(self):
        from modules import brain_entry
        self.assertEqual(list(inspect.signature(brain_entry._install_route_guard).parameters), ["runtime"])


class FileTargetAuthorityTests(unittest.TestCase):
    """İkinci dosya hedefi seçici kalmaz; deterministik/domain yardımcıları durur."""

    def dispatch_intents(self):
        tree = ast.parse(source("engine_intents"))
        dispatch = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "dispatch")
        return {node.pattern.value.pattern.value for node in ast.walk(dispatch)
                if isinstance(node, ast.MatchCase) and isinstance(node.pattern, ast.MatchValue)
                and isinstance(node.pattern.value, ast.Constant)}

    def test_second_file_target_resolver_is_gone(self):
        for filename in ("main_documents", "engine_tools"):
            self.assertNotIn("_resolve_doc", identities(source(filename)), filename)

    def test_legacy_doc_intents_are_not_dispatched(self):
        self.assertFalse(self.dispatch_intents() & RETIRED_IDENTIFIERS)
        self.assertIn("file_action", self.dispatch_intents())

    def test_domain_file_helpers_survive(self):
        for name in ("_file_command", "_folder_overview", "_translate_file", "_keep_photo", "_photo_action"):
            self.assertIn(name, identities(source("main_documents")), name)

    def test_file_ask_exempt_policy_survives(self):
        from modules import brain_understanding
        self.assertTrue(brain_understanding._FILE_ASK_EXEMPT)


class LiveContextParityTests(unittest.TestCase):
    """Live, kendi özel context/authority snapshot'ını kurmaz; assembly salt-okunurdur."""

    def live_prompt_body(self):
        text = source("engine_voice")
        return text[text.index("def _live_prompt"):text.index("def ", text.index("def _live_prompt") + 4)]

    def test_live_has_no_private_history_or_pronoun_resolver(self):
        self.assertNotIn("_context_prompt", identities(source("engine_voice")))
        self.assertNotIn("_context_prompt", identities(source("engine_runtime")))

    def test_live_prompt_selects_no_facts_without_the_canonical_relevance_gate(self):
        body = self.live_prompt_body()
        self.assertNotIn('"facts"', body)
        self.assertEqual(re.findall(r"learning\.(knowledge_prompt|rules_prompt)\(runtime\.profile\)", body), [])
        self.assertTrue(re.search(r"learning\.knowledge_prompt\(runtime\.profile,\s*query\)", body))
        self.assertTrue(re.search(r"learning\.rules_prompt\(runtime\.profile,\s*query\)", body))

    def test_pending_prompt_is_read_only_and_the_mark_has_an_owner(self):
        text = source("learning")
        start = text.index("def pending_prompt")
        body = text[start:text.index("\n\n\n", start)]
        self.assertNotIn("profile.save()", body)
        self.assertIn("def pending_ask_due", text)
        self.assertIn("def mark_pending_ask", text)

    def test_session_open_event_owns_the_write(self):
        self.assertIn("def live_session_opened", source("engine_voice"))
        self.assertIn("live_session_opened", source("engine_loop"))


class LiveToolAuthorityTests(unittest.TestCase):
    """Effect üreten Live araçları canonical request üretir; raw service executor kalmaz."""

    def test_runner_has_no_raw_music_or_task_service_bypass(self):
        text = source("live_tool_runner")
        self.assertNotIn("_direct_tool(services._play_music", text)
        self.assertNotIn("_direct_tool(services._add_handoff", text)

    def test_music_and_handoff_requests_are_canonical_sentences(self):
        from modules.live_tools import _build_request
        self.assertEqual(_build_request("muzik_cal", {"sorgu": "ars viwandi", "platform": "youtube"}),
                         "youtube'da ars viwandi çal")
        self.assertEqual(_build_request("gorev_ekle", {"metin": "sunucuyu kontrol et", "yer": "iş"}),
                         "iş listesine sunucuyu kontrol et ekle")

    def test_live_music_and_task_executors_are_retired(self):
        text = source("live")
        self.assertNotIn("_play_music", identities(text))
        self.assertNotIn("_add_handoff", identities(text))

    def test_transport_domain_tools_keep_their_fence(self):
        text = source("live_tool_runner")
        self.assertIn("prepare_tool", text)
        self.assertIn("prepare_tool", source("engine_voice"))


class CommandManagerFrontDoorTests(unittest.TestCase):
    """Tablo isteği exact/bounded bir kapıdır; herhangi bir cümleyi keyword conjunction ile tüketmez."""

    def test_table_request_recognizer_is_bounded(self):
        from modules import brain_gates
        for phrase in ("tabloya çevir", "bunu tablo yap", "tablo haline getir", "bu yanıtı tabloya çevir"):
            self.assertTrue(brain_gates.table_request(phrase), phrase)
        for unrelated in ("tabloda hangi sensörler yazıyordu", "ben tabureyi sevmem",
                          "yarınki toplantıda tablo gösterme, özeti söyle", "table of contents ne demek",
                          "tabloya bak ve bana kahve tarifi ver"):
            self.assertFalse(brain_gates.table_request(unrelated), unrelated)

    def test_dispatch_uses_the_bounded_recognizer(self):
        self.assertIn("table_request", identities(source("command_manager")))
        self.assertNotIn("(tablo\\w*|table|toplo)", source("command_manager"))


if __name__ == "__main__":
    unittest.main()
