"""PR10c final cutover sözleşmeleri: production'da ikinci semantic authority kalmaz.

Katmanlar: (1) caller-zero/statik authority, (2) router retirement, (3) file target authority,
(4) Live context parity/read-only, (5) Live tool authority, (6) command_manager bounded gate,
(7) yeni ikinci authority'ye karşı kanıtlı allowlist muhafızı.
Her test ya bir modülün fiziksilğini ya da davranışsal bir fail-closed sınırını ölçer; hiçbir
test legacy zinciri authority olarak kabul etmez. Yorum satırı/docstring taraması yapılmaz:
statik kontroller AST üzerinden gerçek kimliklere (import, isim, nitelik, intent sabiti) bakar.
"""
import ast
import importlib.util
import inspect
import re
import unittest
from unittest.mock import patch
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


def imported_modules(text: str):
    """Modül kimliği yalnızca gerçek import'tan anlaşılır: ada göre yorumlanan yerel sembol
    (örn. finance'ın kendi `freshness` yardımcısı) legacy router zinciri sayılmaz."""
    found = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[-1])
                if alias.asname:
                    found.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[-1])
            found |= {alias.name for alias in node.names}
    return found


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
        elif isinstance(node, ast.match_case) and isinstance(node.pattern, ast.MatchValue):
            if isinstance(node.pattern.value, ast.Constant) and isinstance(node.pattern.value.value, str):
                found.add(node.pattern.value.value)
    return found - {None}


def production_authorities():
    for path in sorted(MODULES.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        yield path.name, imported_modules(text), identities(text)


# --- G katmanı: tarama evreni ve kanıtlı allowlist -----------------------------------------------
# Muhafızın gördüğü alan production'ın ta kendisidir: modüller, web köprüleri ve main.
PRODUCTION_FILES = (tuple(sorted(MODULES.glob("*.py"))) + tuple(sorted(ROOT.glob("web*.py")))
                    + tuple(path for path in (ROOT / "main.py",) if path.exists()))


def production_trees():
    for path in PRODUCTION_FILES:
        yield path.name, ast.parse(path.read_text(encoding="utf-8"))


# Core handler'ın istek kararı bu anahtar çiftiyle taşınır; ikisini birlikte üreten her modül
# fiilen ikinci sınıflandırıcıdır. Rastgele "intent" kelimesi değil, sözlük literali taranır.
BRAIN_TURN_DOORS = frozenset({"prepare", "handoff", "bind", "route_command", "run_step"})
# Semantic kapı isimleri: buradan yapılan her yazım bir authority kurulumudur.
SEMANTIC_DOORS = frozenset({"route", "classify", "handle", "intent_router", "_resolve_doc",
                            "_live_command", "_context_prompt", "ask", "chat"})

ROUTE_DICT_ALLOWLIST = {
    "brain_entry.py": "Kararı kendisi üretmez; bu turn'ün prepare() sonucunu Core handler şekline "
                      "izdüşüren tek yer (_legacy_route_projection/route_command).",
}
BRAIN_TURN_ALLOWLIST = {
    # Yüzey girdisi -> {çağrılan kapılar, neden}. Text/Web/kuyruk-audio/telefon/fotoğraf tek turda hazırlanır.
    "engine_loop.py": ({"prepare", "handoff", "bind"},
                       "Tek yüzey girdisi: motor olay döngüsü Brain turünü burada hazırlar ve Core'a devreder."),
    "engine_live_brain.py": ({"prepare", "handoff"},
                             "Live'ın canonical turu: _live_command aynı prepare→handoff kapısından geçer."),
    "engine_commands.py": ({"route_command"},
                           "Core handler'ın tek sınıflandırılmış-istek kapısı çağrısı; başka çağran yok."),
}
SEMANTIC_DOOR_ALLOWLIST = {
    "brain_entry.py": {"route": "_install_job_guard kararı değiştirmez; yalnız canonical "
                                "job.resume/job.cancel eşleşmesinde bounded işaretini OR eder."},
    "engine_runtime.py": {"handle": "EngineContext.__init__'in kendi facade bağlaması: tek giriş handle_request."},
}


def route_decision_dict_files(trees=None):
    return {name for name, tree in (trees or production_trees())
            if any(isinstance(node, ast.Dict) and _dict_string_keys(node) >= {"intent", "args"}
                   for node in ast.walk(tree))}


def brain_turn_caller_map(trees=None):
    found: dict[str, set[str]] = {}
    for name, tree in (trees or production_trees()):
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "brain_entry" and node.attr in BRAIN_TURN_DOORS):
                found.setdefault(name, set()).add(node.attr)
    return found


def semantic_door_write_map(trees=None):
    found: dict[str, set[str]] = {}
    for name, tree in (trees or production_trees()):
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setattr":
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    found.setdefault(name, set()).add(str(node.args[1].value))
                    continue
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in SEMANTIC_DOORS:
                    found.setdefault(name, set()).add(target.attr)
    return found


def _dict_string_keys(node: ast.Dict):
    return {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}


class RetiredModuleTests(unittest.TestCase):
    """Legacy router zinciri ikamet etmez: dosyalar fiziksel olarak kaldırılmış olmalı."""

    def test_retired_semantic_modules_are_physically_gone(self):
        for name in RETIRED_MODULES:
            self.assertIsNone(importlib.util.find_spec(f"modules.{name}"), f"modules/{name}.py hâlâ duruyor")
            self.assertFalse((MODULES / f"{name}.py").exists(), f"modules/{name}.py silinmemiş")

    def test_no_production_source_references_the_retired_authorities(self):
        offenders = []
        for filename, imports, names in production_authorities():
            offenders += [f"{filename}:{name}" for name in sorted(imports & RETIRED_MODULES)]
            offenders += [f"{filename}:{name}" for name in sorted(names & RETIRED_IDENTIFIERS)]
        self.assertEqual(offenders, [])

    def test_legacy_classifier_chain_has_no_production_caller(self):
        for filename in ("engine_commands", "engine_tools", "engine_intents", "command_manager"):
            self.assertNotIn("classify", identities(source(filename)), filename)

    def test_engine_facade_does_not_export_the_legacy_classifier(self):
        from modules import engine_runtime
        self.assertNotIn("intent_router", engine_runtime._DEPENDENCIES)
        self.assertNotIn("route", engine_runtime._HANDLERS["engine_tools"])
        self.assertNotIn("_resolve_doc", engine_runtime._HANDLERS["engine_tools"])
        context = engine_runtime.EngineContext()
        for name in ("intent_router", "route", "_resolve_doc", "_context_prompt"):
            self.assertFalse(hasattr(context, name), name)


class CanonicalRouteAuthorityTests(unittest.TestCase):
    """Core handler'ın istek kapısının tek implementation'ı Brain izdüşümüdür; monkeypatch yok."""

    def bound(self, entry):
        from modules import brain_entry
        return patch.object(brain_entry, "current", return_value=entry)

    def test_route_command_projects_the_bound_entry(self):
        from modules import brain_entry
        entry = SimpleNamespace(text="raporu özetle")
        with self.bound(entry), patch.object(brain_entry, "_legacy_route_projection",
                                             return_value={"intent": "task", "args": {}}) as project:
            self.assertEqual(brain_entry.route_command(SimpleNamespace(), entry.text),
                             {"intent": "task", "args": {}})
            project.assert_called_once_with(entry)

    def test_route_command_without_a_bound_entry_fails_closed(self):
        from modules import brain_entry
        with patch.object(brain_entry, "current", return_value=None), patch.object(
                brain_entry, "_legacy_route_projection",
                side_effect=AssertionError("bağlantısız cümle yorumlandı")):
            decision = brain_entry.route_command(SimpleNamespace(), "raporu özetle")
        self.assertEqual(decision["intent"], "clarify")
        self.assertIn("işlem başlatılmadı", decision["args"]["question"])

    def test_route_command_refuses_a_nested_step(self):
        from modules import brain_entry
        entry = SimpleNamespace(text="raporu özetle")
        with self.bound(entry):
            step = brain_entry.route_command(SimpleNamespace(_typo_pass=False), "sesi 30 yap")
        self.assertEqual(step["intent"], "clarify")
        self.assertIn("adımı", step["args"]["question"])

    def test_engine_facade_has_no_route_door_to_wrap(self):
        from modules import engine_runtime
        self.assertNotIn("route", engine_runtime._HANDLERS["engine_tools"])
        self.assertFalse(hasattr(engine_runtime.EngineContext(), "route"))

    def test_core_handler_uses_the_projection_by_name(self):
        used = identities(source("engine_commands"))
        self.assertIn("route_command", used)
        self.assertNotIn("runtime.route", source("engine_commands"))

    def test_route_guard_monkeypatch_is_gone(self):
        text = source("brain_entry")
        for name in ("_install_route_guard", "canonical_route", "_brain_route_guard_installed"):
            self.assertNotIn(name, text)
        self.assertNotIn("runtime._brain_legacy_route", text)


class FileTargetAuthorityTests(unittest.TestCase):
    """İkinci dosya hedefi seçici kalmaz; deterministik/domain yardımcıları durur."""

    def dispatch_intents(self):
        tree = ast.parse(source("engine_intents"))
        dispatch = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "dispatch")
        return {node.pattern.value.value for node in ast.walk(dispatch)
                if isinstance(node, ast.match_case) and isinstance(node.pattern, ast.MatchValue)
                and isinstance(node.pattern.value, ast.Constant)}

    def test_second_file_target_resolver_is_gone(self):
        for filename in ("main_documents", "engine_tools"):
            self.assertNotIn("_resolve_doc", identities(source(filename)), filename)

    def test_legacy_doc_intents_are_not_dispatched(self):
        self.assertFalse(self.dispatch_intents() & RETIRED_IDENTIFIERS)
        self.assertIn("file_action", self.dispatch_intents())

    def test_domain_file_helpers_survive(self):
        for name in ("_file_command", "_translate_file", "_keep_photo", "_photo_action"):
            self.assertIn(name, identities(source("main_documents")), name)

    def test_folder_listing_has_one_domain_owner(self):
        # İkinci hedef seçiciyle gelen klasör listesi yardımcısı silinir; sahibi folder_analysis kalmalı.
        self.assertNotIn("_folder_overview", identities(source("main_documents")))
        self.assertNotIn("_folder_overview", identities(source("engine_tools")))
        self.assertIn("folder_analysis", imported_modules(source("engine_tools")))

    def test_doc_only_fallback_helpers_retired_with_their_caller(self):
        # Bu yardımcıların tek çağrısı legacy doc_* case'leriydi; hedef seçiciyle birlikte kalktı.
        for name in ("_summarize_chat", "_study_answer", "_explicit_output_format"):
            for filename in ("engine_output", "engine_tools", "engine_intents", "main_documents"):
                self.assertNotIn(name, identities(source(filename)), f"{filename}:{name}")

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
        self.assertNotIn('"goals"', body)
        # Bağlantı anında çözülecek bir soru yoktur; Live kendi bellek/geçmiş seçicisini kuramaz.
        self.assertEqual(re.findall(r"learning\.(knowledge_prompt|rules_prompt)", body), [])
        self.assertNotIn("_recent_turns", body)
        # Assembly salt-okunur: burada profil yazan hiçbir çağrı yok.
        self.assertNotIn("save", body)

    def test_memory_relevance_has_one_canonical_owner(self):
        # Soru-bağımlı ilgi seçiminin tek sahibi profile.system_prompt(query); her yüzey oradan geçer.
        text = source("personalization")
        self.assertTrue(re.search(r"learning\.knowledge_prompt\(self,\s*query\)", text))
        self.assertTrue(re.search(r"learning\.rules_prompt\(self,\s*query\)", text))

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
        # Servis fonksiyonuna giden tek çit kalmadı: _direct_tool yalnız domain protokol araçlarında.
        text = source("live_tool_runner")
        self.assertNotIn("_direct_tool(services.", text.replace(" ", ""))
        self.assertEqual(text.count("_direct_tool"), 2)

    def test_music_and_handoff_requests_are_canonical_sentences(self):
        # Cümleler, yazılı yüzeyin deterministik domain gramerlerinin birebir kendisidir.
        from modules.live_tools import _build_request
        self.assertEqual(_build_request("muzik_cal", {"sorgu": "ars viwandi", "platform": "youtube"}),
                         "youtube'da ars viwandi çal")
        self.assertEqual(_build_request("gorev_ekle", {"metin": "sunucuyu kontrol et", "yer": "iş"}),
                         "iş için not: sunucuyu kontrol et")
        self.assertEqual(_build_request("gorev_ekle", {"metin": "sunucuyu kontrol et", "yer": "genel"}),
                         "görev ekle: sunucuyu kontrol et")
        self.assertIsNone(_build_request("muzik_cal", {"sorgu": ""}))

    def test_canonical_sentences_reach_the_domain_owners(self):
        from modules import handoff, media
        with patch.object(media, "youtube", return_value="Açtım.") as yt:
            self.assertEqual(media.handle("youtube'da ars viwandi çal"), "Açtım.")
            yt.assert_called_once_with("ars viwandi")
        self.assertEqual(handoff.parse("iş için not: sunucuyu kontrol et", "iş için not: sunucuyu kontrol et"),
                         ("Sunucuyu kontrol et", "is", handoff.date.today()))

    def test_live_music_and_task_executors_are_retired(self):
        text = source("live")
        self.assertNotIn("_play_music", identities(text))
        self.assertNotIn("_add_handoff", identities(text))

    def test_transport_domain_tools_keep_their_fence(self):
        # Ses ve yanlış-duyma araçlarının Text yüzeyi grameri yok: domain owner'da kalır, fence korunur.
        self.assertIn("prepare_tool", identities(source("live_tool_runner")))
        self.assertIn("prepare_live_tool", identities(source("engine_voice")))
        self.assertIn("self.prepare_tool", source("live_tool_runner"))


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


class SecondAuthorityGuardTests(unittest.TestCase):
    """G: yeni bir ikinci semantic authority production'a girdiği an bu testler RED olur.

    Allowlist yalnız kanıtlı kimlikleri taşır; allowlist'teki bir yol artık yoksa eşitlik
    bozulur (ölü izin) ve taramanın yakaladığı yeni bir yol varsa yine bozulur (yetki genişletme
    yorumla değil davranışla olur)."""

    def test_route_decision_authority_is_singular(self):
        self.assertEqual(route_decision_dict_files(), set(ROUTE_DICT_ALLOWLIST))

    def test_brain_turn_entries_have_only_the_allowlisted_surface_owners(self):
        self.assertEqual(brain_turn_caller_map(),
                         {name: set(rows) for name, (rows, _) in BRAIN_TURN_ALLOWLIST.items()})

    def test_no_extra_semantic_door_is_installed_at_runtime(self):
        self.assertEqual(semantic_door_write_map(),
                         {name: set(rows) for name, rows in SEMANTIC_DOOR_ALLOWLIST.items()})

    def test_allowlist_rows_each_state_a_reason(self):
        for text in ROUTE_DICT_ALLOWLIST.values():
            self.assertTrue(text.strip())
        for _, reason in BRAIN_TURN_ALLOWLIST.values():
            self.assertTrue(reason.strip())
        for reasons in SEMANTIC_DOOR_ALLOWLIST.values():
            for reason in reasons.values():
                self.assertTrue(reason.strip())

    def test_scan_detects_a_planted_second_authority(self):
        planted = ast.parse(
            'def route(o):\n'
            '    o.handle = lambda c: {"intent": "chat", "args": {}}\n'
            '    setattr(o, "classify", None)\n'
            '    return brain_entry.prepare()\n')
        trees = [("modules/planted_second_authority.py", planted)]
        self.assertEqual(route_decision_dict_files(trees), {"modules/planted_second_authority.py"})
        self.assertEqual(brain_turn_caller_map(trees), {"modules/planted_second_authority.py": {"prepare"}})
        self.assertEqual(semantic_door_write_map(trees), {"modules/planted_second_authority.py": {"handle", "classify"}})

    def test_scan_does_not_flag_lookalike_names(self):
        # Bir payload'taki "intent" anahtarı, yorumdaki "route" kelimesi ve sıradan bir metot
        # çağrısı authority kurulumu değildir; muhafız yalnız kurulumu (atama/setattr) görür.
        tree = ast.parse('payload = {"intent": "mail", "limit": 5}  # route\nclassify = None\n'
                         'context.handle("teşekkürler")\n')
        self.assertEqual(route_decision_dict_files([("lookalike.py", tree)]), set())
        self.assertEqual(semantic_door_write_map([("lookalike.py", tree)]), {})


if __name__ == "__main__":
    unittest.main()
