"""Komut Merkezi kontrolleri hem unittest yayın akışında hem pytest'te çalışır."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "webui" / "nx.js").read_text(encoding="utf-8")
CSS = (ROOT / "webui" / "nx.css").read_text(encoding="utf-8")
WEB = (ROOT / "web.py").read_text(encoding="utf-8")


class CommandCenterTests(unittest.TestCase):
    def test_home_uses_live_jobs_calendar_and_composer(self):
        home = JS[JS.index("PAGES.home="):JS.index("ACT.goset=")]
        for target in ("dockhost", "home-jobs", "home-calendar"):
            self.assertIn(f'id="{target}"', home)
        self.assertIn("JarvisTeam?.refreshHome", JS)

    def test_desktop_has_profile_notifications_and_clock(self):
        top = JS[JS.index("function renderTop()"):JS.index("function needCount()")]
        self.assertIn('data-act="user"', top)
        self.assertIn('data-act="notif"', top)
        self.assertIn('id="clock"', top)

    def test_home_github_button_uses_existing_safe_action(self):
        self.assertIn('data-act="ghpublish"', JS)
        self.assertIn("ACT.ghpublish=async", JS)
        self.assertIn("github_publish", JS)

    def test_snapshot_exposes_local_github_status(self):
        self.assertIn('github_state = _updater.status()', WEB)
        self.assertIn('"github": github_state', WEB)

    def test_command_center_responsive_rules_exist(self):
        for text in (".workspace-hero", ".workspace-settings", "@media(max-width:620px)"):
            self.assertIn(text, CSS)


if __name__ == "__main__":
    unittest.main()
