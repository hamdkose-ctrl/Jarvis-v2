"""Komut Merkezi kontrolleri hem unittest yayın akışında hem pytest'te çalışır."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "webui" / "nx.js").read_text(encoding="utf-8")
CSS = (ROOT / "webui" / "nx.css").read_text(encoding="utf-8")
HOME = (ROOT / "webui" / "home-console.js").read_text(encoding="utf-8")
HOME_CSS = (ROOT / "webui" / "home-console.css").read_text(encoding="utf-8")
WEB = (ROOT / "web.py").read_text(encoding="utf-8")


class CommandCenterTests(unittest.TestCase):
    def test_home_uses_live_specialists_calendar_and_composer(self):
        home = JS[JS.index("PAGES.home="):JS.index("ACT.goset=")]
        self.assertIn("JarvisHome.mount(pg)", home)
        for target in ("compose", "home-expert", "news-list", "home-messages"):
            self.assertIn(f'id="{target}"', HOME)
        self.assertIn("team_snapshot", HOME)
        self.assertIn("void say(text, true)", HOME)
        self.assertNotIn("console-portrait", CSS + JS)

    def test_console_keeps_settings_and_profile_inside_one_screen(self):
        for target in ("conversation-modes", "home-office", "home-workspace"):
            self.assertIn(f'id="{target}"', HOME)
        self.assertIn('data-act="user"', HOME)
        self.assertIn('data-act="notif"', HOME)
        self.assertIn('window.JarvisHome.showWorkspace(S.page,navigation)', JS)
        self.assertNotIn('workspace-sidebar', (ROOT / "webui" / "nx.html").read_text(encoding="utf-8"))

    def test_home_github_button_uses_existing_safe_action(self):
        self.assertIn('data-act="ghpublish"', JS)
        self.assertIn("ACT.ghpublish=async", JS)
        self.assertIn("github_publish", JS)

    def test_snapshot_exposes_local_github_status(self):
        self.assertIn('github_state = _updater.status()', WEB)
        self.assertIn('"github": github_state', WEB)

    def test_command_center_responsive_rules_exist(self):
        self.assertIn("#home-workspace", HOME_CSS)
        self.assertIn(".workspace-settings", CSS)
        self.assertIn(".jarvis-console .layout", HOME_CSS)
        self.assertIn("@media(max-width: 900px)", HOME_CSS)


if __name__ == "__main__":
    unittest.main()
