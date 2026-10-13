import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class V512MaintenanceTests(unittest.TestCase):
    def test_github_real_verification_states_local_changes(self):
        import updater
        info = {"sha": "abcdef123456", "msg": "remote", "date": "2026-10-05"}
        with patch.object(updater, "latest", return_value=info), \
             patch.object(updater, "_state", return_value={"sha": "abcdef123456"}), \
             patch.object(updater, "_source_changes_against", return_value=["main.py"]), \
             patch.object(updater, "_save_state"):
            out = updater.verify_sync()
        self.assertTrue(out["verified"])
        self.assertEqual(out["sync_state"], "local_changes")
        self.assertEqual(out["local_change_count"], 1)

    def test_dependency_lock_is_generated_from_active_venv(self):
        from modules import dependencies
        fake = types.SimpleNamespace(returncode=0, stdout="requests==2.32.5\npsutil==7.0.0\nPillow==11.0.0\nopenpyxl==3.1.5\nreportlab==4.4.0\n", stderr="")
        with tempfile.TemporaryDirectory() as td, \
             patch.object(dependencies, "LOCK", Path(td) / "requirements.lock.txt"), \
             patch.object(dependencies, "in_venv", return_value=True), \
             patch.object(dependencies.subprocess, "run", return_value=fake):
            out = dependencies.create_lock()
            text = dependencies.LOCK.read_text(encoding="utf-8")
        self.assertEqual(out["count"], 5)
        self.assertIn("requests==2.32.5", text)

    def test_phone_security_controls_and_long_token_exist(self):
        phone = (ROOT / "modules" / "phone.py").read_text(encoding="utf-8")
        ui = (ROOT / "webui" / "nx.js").read_text(encoding="utf-8")
        self.assertIn("secrets.token_urlsafe(24)", phone)
        for text in ("Anahtarı yenile", "Yalnız Tailscale", "HTTPS’i aç", "phone_token_reset", "tailscale_https"):
            self.assertIn(text, ui if text not in ("phone_token_reset", "tailscale_https") else (ROOT / "web.py").read_text(encoding="utf-8") + ui)

    def test_google_production_flow_and_key_warning_exist(self):
        ui = (ROOT / "webui" / "nx.js").read_text(encoding="utf-8")
        ga = (ROOT / "modules" / "google_api.py").read_text(encoding="utf-8")
        self.assertIn("Production yaptım", ui)
        self.assertIn("google_oauth_production", ga)
        self.assertIn("Gemini anahtarı yok", ui)
        self.assertIn("home-key-warning", ui)

    def test_legacy_ui_removed_and_not_imported(self):
        # 2026-10-05: eski Tk pencere arayüzü kaldırıldı; tek arayüz web Komut Merkezi.
        gui = (ROOT / "gui.py").read_text(encoding="utf-8")
        for name in ("pages", "pages2", "panel", "chatview", "theme"):
            self.assertNotIn(f"from {name} import", gui, name)
            self.assertNotIn(f"import {name}\n", gui, name)

    def test_version_notes_are_consolidated(self):
        self.assertTrue((ROOT / "docs" / "DEGISIKLIKLER.md").exists())
        self.assertFalse((ROOT / "DEGISIKLIKLER_v5.11.md").exists())
        self.assertFalse((ROOT / "DUZELTMELER_v5.8.md").exists())
        text = (ROOT / "docs" / "DEGISIKLIKLER.md").read_text(encoding="utf-8")
        self.assertIn("v5.12", text)
        self.assertIn("Birleştirilmiş eski sürüm notları", text)

    def test_installer_prefers_lock_file(self):
        bat = (ROOT / "scripts" / "kurulum.bat").read_text(encoding="utf-8")
        self.assertIn("requirements.lock.txt", bat)
        # Kurulum, pip'i doğrudan sanal ortamın python'u ile çağırır: "...python.exe -m pip install -r ...lock.txt"
        self.assertRegex(bat, r"pip install -r \"?[^\n]*requirements\.lock\.txt")

    def test_publish_can_commit_deletions_without_force(self):
        src = (ROOT / "modules" / "git_publish.py").read_text(encoding="utf-8")
        self.assertIn('"sha": None', src)
        self.assertIn('"force": False', src)
        self.assertIn("dependencies.create_lock()", src)


if __name__ == "__main__":
    unittest.main()
