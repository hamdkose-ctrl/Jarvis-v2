"""Komut Merkezi kontrolleri hem unittest yayın akışında hem pytest'te çalışır."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "webui" / "nx.js").read_text(encoding="utf-8")
CSS = (ROOT / "webui" / "nx.css").read_text(encoding="utf-8")
WEB = (ROOT / "web.py").read_text(encoding="utf-8")


class CommandCenterTests(unittest.TestCase):
    def test_home_command_center_sections_exist(self):
        for text in ("Sistem Durumu", "Canlı Aktivite", "Yaklaşan Hatırlatmalar", "GitHub’a Yükle"):
            self.assertIn(text, JS)
        # Hamdi'nin kararı: ana ekranda "AI ve Bağlantılar" kartı ve GitHub kartı yok; GitHub işlevi Ayarlar › Gelişmiş'tedir.
        self.assertNotIn("AI ve Bağlantılar", JS)
        self.assertNotIn('class="card hcard hgit"', JS)
        self.assertIn("function githubBox()", JS)
        self.assertIn("heyTxt()", JS)

    def test_weather_is_visible_next_to_clock(self):
        top = JS[JS.index("function renderTop()"):JS.index("function tcFirst(")]
        self.assertIn('class="tw"', top)
        self.assertIn("w.temp+'°C'", top)
        self.assertIn('id="clock"', top)
        self.assertIn(".tw", CSS)

    def test_home_github_button_uses_existing_safe_action(self):
        self.assertIn('data-act="ghpublish"', JS)
        self.assertIn("ACT.ghpublish=async", JS)
        self.assertIn("github_publish", JS)

    def test_snapshot_exposes_local_github_status(self):
        self.assertIn('github_state = _updater.status()', WEB)
        self.assertIn('"github": github_state', WEB)

    def test_command_center_responsive_rules_exist(self):
        for text in (".home-command", "@media(max-width:1180px)", "@media(max-width:850px)"):
            self.assertIn(text, CSS)


if __name__ == "__main__":
    unittest.main()
