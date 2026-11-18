import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ArchitectureV57Tests(unittest.TestCase):
    def test_updater_check_is_read_only_by_default(self):
        import updater
        info = {"sha": "abc123", "msg": "test", "date": "2026-10-05"}
        with patch.object(updater, "latest", return_value=info), \
             patch.object(updater, "_state", return_value={"sha": "old"}), \
             patch.object(updater, "_compare_commits", return_value="unknown"), \
             patch.object(updater, "_save_state"), \
             patch.object(updater, "apply") as apply:
            msg = updater.check(apply_now=False, force=True)
            self.assertIn("kurulmadı", msg)
            apply.assert_not_called()

    def test_user_provider_keys_have_separate_profile_files(self):
        src = Path("modules/llm.py").read_text(encoding="utf-8")
        self.assertIn('f"{slug}.txt"', src)
        self.assertIn('f"{slug}.groq.txt"', src)
        self.assertIn("user_groq_key(current_user())", src)
        self.assertNotIn("key = config.get_groq_key()", src)
        # Genel (kullanıcısız) Groq anahtar yüzeyi kaldırıldı: tek sahip kullanıcı
        # profilindeki llm.user_groq_key/set_user_groq_key'dir (MIMARI_KURALLAR v5.7).
        conf = Path("config.py").read_text(encoding="utf-8")
        for retired in ("GROQ_KEY_FILE", "def save_groq_key", "def get_groq_key", "GROQ_API_KEY"):
            self.assertNotIn(retired, conf)

    def test_update_refuses_unpublished_local_changes(self):
        import updater
        with patch.object(updater, "_protected_local_changes", return_value={"main.py": {"sha256": "x"}}):
            with self.assertRaisesRegex(RuntimeError, "yerel kaynak"):
                updater.apply({"sha": "x", "msg": "x", "date": "x"})

if __name__ == "__main__":
    unittest.main()
