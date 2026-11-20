from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "local_model_acceptance.py"


class LocalModelAcceptanceBootstrapTests(unittest.TestCase):
    def test_script_bootstraps_repo_root_outside_repo_cwd(self):
        code = (
            "import runpy; "
            f"runpy.run_path({str(SCRIPT)!r}, run_name='local_model_acceptance_bootstrap_probe'); "
            "import modules; "
            "print(modules.__name__)"
        )
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", code],
                cwd=cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("modules", proc.stdout.splitlines())

    def test_browser_acceptance_uses_real_ai_menu_action_before_ollama_render(self):
        src = SCRIPT.read_text(encoding="utf-8")
        menu_selector = '[data-act=\\"mnopen\\"][data-k=\\"ai\\"]'
        open_ai = 'dispatch_event("click")'
        wait_panel = 'page.wait_for_selector("#spane"'
        select_ollama = "SX.aiSel='ollama'"
        legacy_deep_link = 'page.evaluate("S.sset=\'ai\'; go(\'settings\')")'
        self.assertIn(menu_selector, src)
        self.assertIn(open_ai, src)
        self.assertIn(wait_panel, src)
        self.assertIn(select_ollama, src)
        self.assertLess(src.index(menu_selector), src.index(open_ai))
        self.assertLess(src.index(open_ai), src.index(wait_panel))
        self.assertLess(src.index(wait_panel), src.index(select_ollama))
        self.assertNotIn(legacy_deep_link, src)
        self.assertNotIn("page.wait_for_timeout(800)", src)


    @unittest.skipUnless(importlib.util.find_spec('playwright') is not None,
                         'Playwright (tarayıcı ajanı) bu kurulumda yok; çekirdek ses/PC kurulumu onsuz çalışır')
    def test_browser_probe_does_not_start_a_second_loop_for_server_owned_by_web(self):
        import runpy
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        import playwright.sync_api
        probe=runpy.run_path(str(SCRIPT),run_name='local_model_lifecycle_probe')['_browser_check']
        server=Mock()
        web=SimpleNamespace(_fonts_ready=Mock(),serve=Mock(return_value=(server,'http://127.0.0.1/')))
        with patch.dict(sys.modules,{'web':web}), \
             patch('playwright.sync_api.sync_playwright',side_effect=RuntimeError('stop before browser')), \
             patch('threading.Thread') as thread:
            ok,_=probe(ROOT,{'local_installed_models':[]})
        self.assertFalse(ok)
        web.serve.assert_called_once_with(port=0)
        thread.assert_not_called()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()


class LocalModelAcceptanceCspTests(unittest.TestCase):
    """PC watcher'da görülen EvalError/CSP yarışının kapatıldığı yer (P2-2).

    `page.wait_for_function("<string>")` ilk yoklaması false olan koşulu `new Function` ile
    sayfa dünyasında derliyor; ürün CSP'si 'unsafe-eval' içermediği için bekleme EvalError ile
    kesiliyordu. Koşul ilk yoklamada doğruysa geçiyordu, yani sonuç arayüzün açılış hızına
    bağlıydı. Ağ ve tarayıcı gerektirmez: sahte sayfa ile yoklama yüzeyi ölçülür.
    """

    def _wait_for(self):
        import runpy
        return runpy.run_path(str(SCRIPT), run_name='local_model_csp_probe')['_wait_for']

    def test_the_wait_polls_evaluate_and_never_compiles_a_page_predicate(self):
        wait_for = self._wait_for()
        seen = []

        class Page:
            def __init__(self):
                self.answers = [False, False, True]

            def evaluate(self, condition):
                seen.append(condition)
                return self.answers.pop(0)

            def wait_for_function(self, *args, **kwargs):
                raise AssertionError('CSP altında derleme yapan string predicate kullanılamaz')

        page = Page()
        wait_for(page, "typeof S !== 'undefined' && !!S.snap", 5_000, 'nx.js oturum durumu')
        self.assertEqual(seen, ["typeof S !== 'undefined' && !!S.snap"] * 3)
        self.assertEqual(page.answers, [])

    def test_a_condition_that_never_becomes_true_still_fails_instead_of_being_skipped(self):
        # Düzeltme kontrolü gevşetmez: zaman aşımında betik kendi hatasını söyler, passed olmaz.
        wait_for = self._wait_for()

        class Page:
            def evaluate(self, condition):
                return False

        with self.assertRaises(TimeoutError) as caught:
            wait_for(Page(), "document.body.innerText.includes('Aktif Model')", 60, 'Aktif Model satırı')
        self.assertIn('Aktif Model satırı', str(caught.exception))
        self.assertIn("document.body.innerText.includes('Aktif Model')", str(caught.exception))

    def test_the_script_keeps_no_string_predicated_wait_and_keeps_its_real_checks(self):
        # Yorum/belge satırları değil, gerçek çağrı yüzeyi ölçülür: betikte hiçbir
        # wait_for_function çağrısı kalmamalı ki hiçbir koşul sayfa dünyasında derlenmesin.
        calls = {node.func.attr for node in ast.walk(ast.parse(SCRIPT.read_text(encoding='utf-8')))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertNotIn('wait_for_function', calls)
        src = SCRIPT.read_text(encoding='utf-8')
        for condition in ["typeof S !== 'undefined' && !!S.snap",
                          "typeof ACT.localmodelsave === 'function'",
                          "document.querySelector('#local-model-select').options.length > 0",
                          "document.body.innerText.includes('Aktif Model')"]:
            self.assertIn(condition, src)
        # Ürün CSP'si bu paketin konusu değildir ve gevşetilmez: sunucudaki politika satırı olduğu gibi durur.
        policy = (ROOT / 'web.py').read_text(encoding='utf-8')
        self.assertIn("script-src 'self' 'unsafe-inline'", policy)
        self.assertNotIn("'unsafe-eval'", policy)


if __name__ == "__main__":
    unittest.main()
