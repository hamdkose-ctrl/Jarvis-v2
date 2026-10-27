from __future__ import annotations

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
        menu_ready = 'page.wait_for_selector("[data-act=\\"mnopen\\"][data-k=\\"ai\\"]"'
        open_ai = 'dispatch_event("click")'
        wait_panel = 'page.wait_for_selector("#spane"'
        select_ollama = "SX.aiSel='ollama'"
        self.assertIn(menu_ready, src)
        self.assertIn(open_ai, src)
        self.assertIn(wait_panel, src)
        self.assertIn(select_ollama, src)
        self.assertLess(src.index(menu_ready), src.index(open_ai))
        self.assertLess(src.index(open_ai), src.index(wait_panel))
        self.assertLess(src.index(wait_panel), src.index(select_ollama))
        self.assertNotIn("go('settings')", src)
        self.assertNotIn("page.wait_for_timeout(800)", src)


if __name__ == "__main__":
    unittest.main()
