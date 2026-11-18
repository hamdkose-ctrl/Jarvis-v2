"""Paket 6 kilidi: caller-zero üç ad üretimden kaldırıldı, tek sahipleri yaşıyor.

Silinenler: `publisher_news.multiple_publishers` (iki-yayıncı eşiğinin tek sözleşmesi
`news_pipeline.enough_evidence`), `llm.set_api_key` (fiziksel-deneme tek sahibi
`llm._gemini_http_options`; çalışma zamanı anahtar değişimi kişiye özel `set_user_key`),
`nxapi.reset_file_cache` (tek yenileme yolu `list_files(force=True)`).
"""
import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


RETIRED = (
    ("modules/publisher_news.py", "multiple_publishers"),
    ("modules/llm.py", "set_api_key"),
    ("modules/nxapi.py", "reset_file_cache"),
)
RETIRED_NAMES = tuple(name for _, name in RETIRED)


def _production_py():
    for path in sorted(Path(".").rglob("*.py")):
        rel = path.as_posix()
        if rel.startswith(("tests/", ".venv/", "build/", "dist/")) or "/.venv/" in rel:
            continue
        yield rel, path


def _identifiers(source: str):
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


class RetiredSymbolIsGoneTests(unittest.TestCase):
    def test_symbols_are_physically_absent_from_their_modules(self):
        from modules import llm, nxapi, publisher_news
        modules = {"modules/publisher_news.py": publisher_news,
                   "modules/llm.py": llm, "modules/nxapi.py": nxapi}
        for rel, name in RETIRED:
            self.assertFalse(hasattr(modules[rel], name), f"{rel}:{name} duruyor")
            tree = ast.parse(Path(rel).read_text(encoding="utf-8"))
            top = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            self.assertNotIn(name, top, f"{rel} üst seviyede {name} bağlıyor")

    def test_no_production_file_even_names_them(self):
        for rel, path in _production_py():
            found = _identifiers(path.read_text(encoding="utf-8")) & set(RETIRED_NAMES)
            self.assertFalse(found, f"{rel} hâlâ {sorted(found)} adını kullanıyor")

    def test_bridge_and_ui_do_not_expose_them(self):
        for rel in ("webui/nx.js", "webui/icons.js"):
            p = Path(rel)
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            for name in RETIRED_NAMES:
                self.assertNotIn(name, text, f"{rel} köprüsü {name} çağrısı yapıyor")

    def test_stale_owner_pointer_is_gone_from_benchmark_doc(self):
        text = Path("docs/architecture/JARVIS_RESEARCHWORKER_READONLY_BENCHMARK_V1.md").read_text(encoding="utf-8")
        self.assertNotIn("multiple_publishers", text)
        self.assertIn("news_pipeline.enough_evidence", text)


class SingleOwnerStillLiveTests(unittest.TestCase):
    def test_two_publisher_threshold_lives_in_enough_evidence(self):
        from modules import news_pipeline

        def rows(*urls):
            return [{"news_article": {"url": u}} for u in urls]

        general = "son dakika haberleri"
        self.assertTrue(news_pipeline.enough_evidence(
            rows("https://www.aa.com.tr/a", "https://www.bbc.com/turkce/b"), general))
        self.assertFalse(news_pipeline.enough_evidence(rows("https://www.aa.com.tr/a"), general),
                         "tek yayıncı genel kapsamı kapatamaz")
        self.assertTrue(news_pipeline.enough_evidence(
            rows("https://www.aa.com.tr/a"), "https://www.aa.com.tr/a haberini oku"),
            "açık tek kaynak kendi kapsamıyla değerlendirilir")

    def test_completion_caller_is_still_wired(self):
        self.assertIn("news_pipeline.enough_evidence(verified,request)",
                      Path("modules/news_policy.py").read_text(encoding="utf-8"))

    def test_gemini_clients_have_one_physical_attempt_owner(self):
        from modules import llm
        opts = llm._gemini_http_options()
        self.assertEqual(opts["retry_options"], {"attempts": 1})
        self.assertEqual(opts["timeout"], 45000)
        self.assertIsNot(opts, llm._gemini_http_options(), "istemciler arasında paylaşılırsa biri denemeyi değiştirir")
        src = Path(llm.__file__).read_text(encoding="utf-8")
        self.assertIn("_client = genai.Client(api_key=API_KEY, http_options=_gemini_http_options())", src)
        self.assertIn("genai.Client(api_key=k, http_options=_gemini_http_options())", src)

    def test_per_user_key_remains_the_runtime_change_owner(self):
        from modules import llm
        self.assertTrue(callable(getattr(llm, "set_user_key")))
        src = Path("web_models.py").read_text(encoding="utf-8")
        self.assertIn("runtime.llm.set_user_key(p.slug, key)", src)

    def test_forced_listing_is_the_only_cache_refresh_route(self):
        from modules import nxapi
        with TemporaryDirectory() as td, patch.object(nxapi, "FILES_DIR", Path(td)), \
                patch.object(nxapi, "_scan_files", return_value=[]) as scan:
            saved = dict(nxapi._FILE_CACHE)
            with nxapi._FILE_CACHE_LOCK:
                nxapi._FILE_CACHE.update(rows=None, ts=0.0)
            try:
                nxapi.list_files()
                nxapi.list_files()
                self.assertEqual(scan.call_count, 1, "taze önbellek ikinci isteği taramamalı")
                nxapi.list_files(force=True)
                self.assertEqual(scan.call_count, 2, "force gerçek tarama yapmalı")
            finally:
                with nxapi._FILE_CACHE_LOCK:
                    nxapi._FILE_CACHE.update(saved)
        self.assertIn("nxapi.list_files(force=bool(force))", Path("web_files.py").read_text(encoding="utf-8"))


class OrphanModuleIsGoneTests(unittest.TestCase):
    def test_unreferenced_drawing_module_is_physically_retired(self):
        self.assertFalse(Path("modules/widget_styles.py").exists(),
                         "hiçbir yerden adlandırılmayan çizim modülü duruyor")
        self.assertEqual(list(Path("modules").glob("widget_styles*")), [])
        for rel, path in _production_py():
            self.assertNotIn("widget_styles", path.read_text(encoding="utf-8"),
                             f"{rel} yetim modülü anıyor")

    def test_live_widget_owns_its_own_drawing(self):
        src = Path("modules/widget.py").read_text(encoding="utf-8")
        self.assertIn("COLORS =", src)
        self.assertNotIn("widget_styles", src)


class DeferredResidueIsRecordedTests(unittest.TestCase):
    def test_unowned_contract_vocabulary_is_written_down(self):
        text = Path("docs/BEKLEYEN_ISLER.md").read_text(encoding="utf-8")
        for marker in ("observe_dialog", "two_factor_handoff", "download_receipt", "filesend.set_target"):
            self.assertIn(marker, text, f"{marker} envanterde yok")
        self.assertIn("accept_downloads=False", text, "indirmenin bugün reddedildiği açıkça yazılmalı")


if __name__ == "__main__":
    unittest.main()
