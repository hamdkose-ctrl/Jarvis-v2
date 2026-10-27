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


if __name__ == "__main__":
    unittest.main()
