"""BRAIN-03: ikinci semantic authority sayımı — ölçülmüş, yalnız küçülen defter.

Yasağın kendisi (mimari sözleşme §24/§25, ban 1 ve ban 2): ham doğal cümleyi okuyup capability /
target / effect seçen ikinci bir otorite olamaz; anlam kararı Brain'de bir kez doğar, Core
doğrular, etki kendi sahibinde yürür. Bu dosya o yüzeyi *ad + çağıran-dosya kümesi* olarak
kilitler: sayılan bir kapı ikinci bir çağıran kazanırsa veya bir çağıran kümesi genişlerse test
RED verir; emeklilikte satır silmek ise PR'ın işidir. Kapsam dürüstçe budur: defter **sayılmış
kapıların** sahipliğini kilitler, yoksa yeni bir sembol altında yazılacak ham bir kapıyı keşfetmez.
Yeni bir ham cümle kapısı eklemenin maliyeti süreç kuralıdır — migration map §14'e karar satırı
yazılır ve §13.1 satırı eklenir; keşif ise ayrı nöbetçilerin işidir (`EngineCommandsStructuralGuardTests`
yasak selector token'ları, `test_the_census_covers_every_front_gate_and_cascade_arm` zincir
eşitliği, `BrainNeverDelegatesToARawDoorTests`).

Denetim SHOULD FIX'i burada kapanır: taban `ea2f0b3` ölçümündeki `_source_calls` çıplak ad
eşleştirmesi `from modules.messaging import is_whatsapp_message as probe` gibi bir takmaadı
görmüyordu. Buradaki çözücü import bağlamını çözer ve bunu sentetik kaynakla kendi kendini
kanıtlayarak yapar.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _python_sources():
    return sorted(list(ROOT.glob("*.py")) + list((ROOT / "modules").rglob("*.py"))
                  + list((ROOT / "scripts").glob("*.py")))


def _import_bindings(tree: ast.AST) -> dict[str, str]:
    """Yerel ad → noktalı kaynak yolu (`from a.b import c as d` → {"d": "a.b.c"})."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
    return out


def _dotted(call: ast.Call, bindings: dict[str, str]) -> list[str]:
    """Çağrı yerinin noktalı zinciri, import bağlamı çözülmüş ve halkalara ayrılmış halde.

    `from modules import messaging` + `messaging.quick_parse(x)` → ["modules", "messaging",
    "quick_parse"]; `import modules.messaging as msg` + `msg.quick_parse(x)` aynı zinciri verir.
    Halkalar ayrı durulmazsa ("modules.messaging" tek düğüm) defter çözümlemesi gerçek çağıranları
    görmezden gelir ve sayım sessizce eksilir."""
    parts: list[str] = []
    node = call.func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(bindings.get(node.id, node.id))
    return [segment for part in reversed(parts) for segment in part.split(".")]


_REPO_TREES: list[tuple[str, ast.AST, dict[str, str]]] | None = None


def _repo_trees() -> list[tuple[str, ast.AST, dict[str, str]]]:
    """Repo tozu bir kez ağaçlandırılır: otuz iki kapı için otuz iki kez parse CI süresidir."""
    global _REPO_TREES
    if _REPO_TREES is None:
        built = []
        for path in _python_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            built.append((path.relative_to(ROOT).as_posix(), tree, _import_bindings(tree)))
        _REPO_TREES = built
    return _REPO_TREES


def production_callers(marker: str, sources: dict[str, object] | None = None) -> list[str]:
    """`marker`ı çağıran dosyalar (tanımlar hariç), takma adlar çözülmüş halde.

    `sources` verilirse yalnız o adlar taranır (sentetik/alt küme kanıt); verilmezse repo tozu.
    Yalnız çıplak ad değil, noktalı zincirin son halkaları karşılaştırılır."""
    target = marker.split(".")
    if sources is None:
        scan = _repo_trees()
    else:
        scan = []
        for name, origin in sources.items():
            text = origin if isinstance(origin, str) else origin.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            scan.append((name, tree, _import_bindings(tree)))
    found: set[str] = set()
    for name, tree, bindings in scan:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _dotted(node, bindings)[-len(target):] == target:
                found.add(name)
                break
    return sorted(found)


def attribute_call_sites(attr: str) -> list[str]:
    """Adı `attr` olan yöntemi ALICIDAN BAĞIMSIZ çağıran dosyalar.

    `production_callers` noktalı zinciri çözer; alıcısı kendi bir çağrı olan yazım
    (`runtime._p().set_pref(...)`) zincirde "_p" halkası görünür ve hedefle eşleşmez. Bu süpürme
    çözümleme gerektirmez, bu yüzden geniş (yanlış pozitife açıktır) — "tek sahip" iddialarında
    değil, iddianın ZAYIFLAMADIĞINI göstermek için kullanılır."""
    found: set[str] = set()
    for name, tree, _bindings in _repo_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == attr:
                found.add(name)
                break
    return sorted(found)


def pref_key_writers(key: str) -> list[str]:
    """Bir tercih anahtarını SÖZCÜK olarak yazan/silen dosyalar (`set_pref`, `pop`, `[key] =`)."""
    found: set[str] = set()
    for name, tree, _bindings in _repo_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in {"set_pref", "pop"} and node.args \
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value == key:
                found.add(name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) \
                            and isinstance(target.slice, ast.Constant) \
                            and target.slice.value == key:
                        found.add(name)
    return sorted(found)


class SecondSemanticAuthorityCensusTests(unittest.TestCase):
    """§13.1 ham dil girişlerinin ölçülmüş üretim sahibi; defter yalnız küçülür."""

    # Ölçüm tabanı: origin/main @ 755ddf6 (BRAIN-02 kapanışı) + BRAIN-03 dilim 1 emekliliği.
    # Anahtar, çağrı yerindeki zincirin son halkalarıdır (`runtime._file_command` → "_file_command").
    # Kapı başına SAHİP SETLERİ ölçüldü; emeklilikte set daraltmak PR'ın işidir, genişlemek RED
    # verir. Satır EKLEMEK ölçüm düzeltmesidir (bu dilimde `_mail_handle`: zincirin bir kolu olarak
    # ölçülmüş ama deftere yazılmamıştı — eksik satır, taşınmış bir "defter tam" iddiasıdır).
    RAW_SEMANTIC_DOORS: dict[str, set[str]] = {
        # main.py cascade kolları (engine_commands.handle içindeki ham doğal dil kapıları).
        # BRAIN-03 dilim 2 (emekli): üç kapı da yüzeyden fiziksel olarak silindi; anlam kararı
        # `message.send`/`contacts.manage` önerisinde, biçim Core'da, oturum `pending_msg`'de.
        # Satır silinmez, boş kümeye iner: geri yeni bir çağıran gelirse test RED verir.
        "messaging.is_whatsapp_message": set(),
        "messaging.quick_parse": set(),
        "messaging.extract": set(),
        "_contact_command": set(),
        "learning.handle": set(),  # BRAIN-03 dilim6: legacy semantic owner physically removed
        "_file_command": {"modules/brain_precedence.py", "modules/engine_commands.py",
                          "modules/engine_tools.py", "modules/main_documents.py"},
        "system_control.windows_settings": set(),  # typed Windows Core adapter
        "selfctl.handle": set(),  # typed Jarvis-control Core adapter
        "_user_command": set(),
        "_user_controls": {"modules/brain_precedence.py", "modules/engine_commands.py"},
        "_planner_command": {"modules/brain_precedence.py", "modules/engine_commands.py",
                             "modules/engine_tools.py"},
        "_macro_teach": set(),
        "_macro_manage": set(),
        "_macro_run": {"modules/brain_precedence.py", "modules/engine_tools.py"},
        "_extra_commands": {"modules/brain_precedence.py"},
        # `job_front.wants`, `goal_executor.handle` ve `continue_app` §13.2'nin KEEP satırlarıdır
        # (bounded protokol sahibidir, capability seçmez); burada sayılmalarının nedeni yüzeylerinin
        # sessizce büyümesini durdurmak. Altındaki `_study_intent` ise §13.1/105'in taşınacak kapısıdır.
        "job_front.wants": {"modules/engine_commands.py"},
        "goal_executor.handle": {"modules/engine_commands.py"},
        "continue_app": {"modules/engine_commands.py"},
        "_study_intent": {"modules/engine_commands.py"},
        "hoca.handle": {"modules/engine_tools.py"},
        # `_extra_commands` zincirinin kolları: tek üretim çağıranı zincirin kendisidir.
        "plugins.handle": {"modules/engine_tools.py"},
        "handoff.handle": {"modules/engine_tools.py"},
        "browser.handle": {"modules/engine_tools.py"},
        "tasks.handle": {"modules/engine_tools.py"},
        "kb.handle": {"modules/engine_tools.py"},
        "filesend.handle": {"modules/engine_tools.py"},
        "worktrack.handle": {"modules/engine_tools.py"},
        "files.handle": {"modules/engine_tools.py"},
        "media.handle": {"modules/engine_tools.py"},
        "_mail_handle": {"modules/engine_tools.py"},
        "notify.handle": {"modules/engine_tools.py"},
        "_screen_ocr": {"modules/engine_tools.py", "modules/engine_intents.py"},
    }

    def test_every_raw_semantic_door_has_exactly_its_pinned_production_owner(self):
        for marker, owners in self.RAW_SEMANTIC_DOORS.items():
            with self.subTest(door=marker):
                self.assertEqual(set(production_callers(marker)), owners)

    def test_the_census_covers_every_front_gate_and_cascade_arm(self):
        # Defterin kendisi eksiltilmesin: sıra sözleşmesinin her kolu ve cascade'in her arm'ı
        # yukarıda bir satır olarak durmalıdır.
        from modules import brain_precedence
        gate_doors = {"file_command": "_file_command",
                      "user_controls": "_user_controls",
                      "planner_command": "_planner_command",
                      "macro_run": "_macro_run",
                      "extra_commands": "_extra_commands"}
        self.assertEqual(set(brain_precedence.FRONT_GATES), set(gate_doors))
        for gate in brain_precedence.FRONT_GATES:
            with self.subTest(gate=gate):
                self.assertIn(gate_doors[gate], self.RAW_SEMANTIC_DOORS)

        # engine_commands.handle cascade'inin ham dil arm'ları (migration map §13.1 satırları).
        # Mesaj/rehber kolları dilim 2'de emekli edildi; kalan canlı kollar aşağıdadır.
        cascade_arms = {"learning.handle",
                        "_file_command", "job_front.wants", "goal_executor.handle",
                        "continue_app", "_study_intent", "_screen_ocr",
                        "_mail_handle"}
        self.assertTrue(cascade_arms <= set(self.RAW_SEMANTIC_DOORS),
                        msg=str(sorted(cascade_arms - set(self.RAW_SEMANTIC_DOORS))))

    def test_exact_undo_has_one_core_worker_caller_and_no_raw_parser(self):
        # This is a real AST caller-zero retirement (not a renamed handler).
        self.assertEqual(set(production_callers("undo_organize")),
                         {"modules/engine_intents.py"})
        source = (ROOT / "modules" / "engine_tools.py").read_text(encoding="utf-8")
        start = source.index("def _extra_commands(")
        body = source[start:source.find("\ndef ", start + 1)]
        self.assertNotIn("undo_organize(", body)
        self.assertNotIn("düzenlemey[ie] geri al", body)

    def test_the_retired_city_door_has_no_production_owner_left(self):
        # BRAIN-03 dilim 1: şehir set/reset effect'inin yazma dikişi iki sahibe iner —
        # varsayılanı kuran `engine_context` ve kanonical planı yürüten `engine_intents`.
        # Emekli yüzey (`engine_commands`) ile sıra köprüsü (`brain_precedence`) geri yazamaz;
        # ham cümleden pref yazan bir helper konursa da bu satır RED verir.
        self.assertEqual(set(production_callers("profile.set_pref")),
                         {"modules/engine_context.py", "modules/engine_intents.py"})

    def test_the_receivers_production_callers_cannot_resolve_are_still_swept(self):
        # Zincir çözümü alıcısı bir ÇAĞRI olan yazımı göremez: `runtime._p().set_pref(...)`
        # (web_memory) halkayı "_p" olarak taşır. "tek yazıcı" iddiası bu süpürmeyle ölçülür.
        swept = set(attribute_call_sites("set_pref"))
        self.assertTrue({"modules/engine_context.py", "modules/engine_intents.py",
                         "web_memory.py"} <= swept, msg=str(sorted(swept)))

    def test_the_literal_city_preference_has_exactly_one_writer(self):
        # `prefs["city"]` anahtarını HAM metinden bağımsız, sözcük olarak yazan/silen tek yer
        # kanonical intent sahibidir. UI Ayarlar yolu anahtarı sözcük olarak taşımaz (aşağıdaki
        # test), `engine_context` yolunun anahtarı "rate"/"voice"tir; şehir anahtarı değildir.
        self.assertEqual(set(pref_key_writers("city")), {"modules/engine_intents.py"})

    def test_the_settings_page_city_writer_is_a_direct_user_setting_not_a_language_door(self):
        # `web_memory.pref_set` kullanıcının sayfadardan seçtiği anahtarı kapalı bir listeye göre
        # yazar; cümle okumaz. Bu, "ham dil kapısı emekli oldu" iddiasını zayıflatmaz: iddia
        # yalnız doğal dilden tercih yazan yollar içindir ve burada regex yoktur.
        tree = ast.parse((ROOT / "web_memory.py").read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "pref_set")
        readers = [node for node in ast.walk(method)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in {"match", "search", "fullmatch", "findall"}]
        self.assertEqual(readers, [])
        literals = {node.value for node in ast.walk(method)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        self.assertIn("city", literals)


class AliasAwarenessProofTests(unittest.TestCase):
    """Defterin kendisi kanıtlı olmalı: takma adla gizlenen çağıran bulunur."""

    def test_an_import_alias_does_not_hide_a_raw_door(self):
        plain = {"a.py": "from modules.messaging import is_whatsapp_message\n"
                         "is_whatsapp_message(x)\n"}
        aliased = {"b.py": "from modules.messaging import is_whatsapp_message as probe\n"
                           "probe(x)\n"}
        rebind = {"c.py": "import modules.messaging as msg\n"
                          "msg.is_whatsapp_message(x)\n"}
        self.assertEqual(production_callers("messaging.is_whatsapp_message", plain), ["a.py"])
        self.assertEqual(production_callers("is_whatsapp_message", aliased), ["b.py"])
        self.assertEqual(production_callers("messaging.is_whatsapp_message", rebind), ["c.py"])

    def test_a_definition_alone_is_not_counted_as_a_caller(self):
        only_def = {"d.py": "def is_whatsapp_message(x):\n    return x\n"}
        self.assertEqual(production_callers("messaging.is_whatsapp_message", only_def), [])


class BrainNeverDelegatesToARawDoorTests(unittest.TestCase):
    """Ban 1 ve ban 2 yapısal kilitleri.

    Ban 1: model, bir regex capability'yi önceden bulduğu için onu öneremez — öneri kümesi Core
    kataloğundan doğar, legacy gramerden değil.
    Ban 2: model düşüşü doğal dili keyword sistemine geri bırakamaz — Brain katmanı ham bir kapıyı
    çağırarak anlam türetmez; çekirdek zarfı reddedilirse karar Brain'in kendi deterministik
    Understanding'i veya sohbetin tek sahibidir."""

    def test_the_envelope_can_only_propose_core_catalogued_capabilities(self):
        from modules import brain_core_map, brain_model_understanding

        source = (ROOT / "modules" / "brain_model_understanding.py").read_text(encoding="utf-8")
        self.assertIn("CORE_INTENTS", source)
        self.assertNotIn("LEGACY_OWNED_HINTS", source)
        self.assertIsNone(brain_core_map.core_plan("not.a.real.capability", {}))
        self.assertEqual(sorted(set(brain_core_map.LEGACY_OWNED_HINTS)), [])

    def test_no_brain_layer_module_consults_a_raw_semantic_door(self):
        # Ban 2: Brain katmanı (modules/brain_*.py) hiçbir ham kapıyı çağırarak anlam üretmez.
        # `brain_precedence.py` tek istisnadır: emeklilik boyunca sıra köprüsüdür ve her çağrısı
        # defterin owner kümesinde zaten satır satır sayılmıştır.
        # Çağrı ağacı alt ağaç üzerinde yeniden ölçülür — anahtar kelime süzmesi değil, AST.
        brain_sources = {path.name: path for path in (ROOT / "modules").glob("brain_*.py")
                         if path.name != "brain_precedence.py"}
        self.assertTrue(len(brain_sources) >= 5, msg=str(sorted(brain_sources)))
        for marker in sorted(SecondSemanticAuthorityCensusTests.RAW_SEMANTIC_DOORS):
            with self.subTest(door=marker):
                self.assertEqual(production_callers(marker, brain_sources), [])

    def test_the_retired_city_grammar_lives_only_in_the_canonical_recognizer(self):
        # Toz kümesi üretim kaynaklarıdır (modules/, scripts/, kök .py); testler sayılmaz.
        # "şehrim" dizisini taşıyan üç yer: kanonical tanıyıcı, engine_commands'teki emeklilik
        # notu ve modules/typo.py yazım-düzeltme kelime listesi (gramer değil, sözlük).
        owners = {path.relative_to(ROOT).as_posix() for path in _python_sources()
                  if "şehrim" in path.read_text(encoding="utf-8", errors="replace")}
        self.assertEqual(owners, {"modules/brain_understanding.py",
                                  "modules/engine_commands.py",
                                  "modules/typo.py"})


if __name__ == "__main__":
    unittest.main()
