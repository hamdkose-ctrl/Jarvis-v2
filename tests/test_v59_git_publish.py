import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class V59GitPublishTests(unittest.TestCase):

    def test_manual_publish_requires_same_remote_base(self):
        from modules import git_publish as publish
        with patch.object(publish, "_api", return_value={"object": {"sha": "remote-new"}}), \
             patch("updater.status", return_value={"sha": "local-old"}):
            with self.assertRaisesRegex(RuntimeError, "ileride"):
                publish.publish_worktree("test")

    def test_updater_refuses_any_unpublished_local_source_change(self):
        import updater
        with patch.object(updater, "_protected_local_changes", return_value={}), \
             patch.object(updater, "_local_source_changes", return_value=["main.py"]):
            with self.assertRaisesRegex(RuntimeError, "yerel kaynak"):
                updater.apply({"sha": "new", "msg": "new", "date": "2026-10-05"})

    def test_git_yukle_command_exists(self):
        from modules import git_publish
        engine_commands = (ROOT / "modules" / "engine_commands.py").read_text(encoding="utf-8")
        command_manager = (ROOT / "modules" / "command_manager.py").read_text(encoding="utf-8")
        self.assertIn("exact_admin_view", engine_commands)
        self.assertIn("git_publish.publish_worktree", command_manager)
        self.assertTrue(git_publish.requested("git yükle"))


if __name__ == "__main__":
    unittest.main()
