"""AGENTS.md belge bağlantıları gerçek dosyalarla uyumlu kalır."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentsLinksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cls.paths = set(re.findall(r"\bdocs/[\w./-]+\.md(?![\w./-])", text))

    def test_agent_links_exist(self):
        paths = {path for path in self.paths if path.startswith("docs/agents/")}
        self.assertTrue(paths, "AGENTS.md içinde alan notu bağlantısı bulunamadı")
        missing = sorted(path for path in paths if not (ROOT / path).is_file())
        self.assertEqual(missing, [], f"AGENTS.md alan bağlantıları bulunamadı: {missing}")

    def test_all_agent_documents_are_linked(self):
        actual = {path.relative_to(ROOT).as_posix()
                  for path in (ROOT / "docs" / "agents").rglob("*.md") if path.is_file()}
        missing = sorted(actual - self.paths)
        self.assertEqual(missing, [], f"AGENTS.md içinde listelenmeyen alan notları: {missing}")

    def test_other_doc_links_exist(self):
        paths = {path for path in self.paths if not path.startswith("docs/agents/")}
        missing = sorted(path for path in paths if not (ROOT / path).is_file())
        self.assertEqual(missing, [], f"AGENTS.md belge bağlantıları bulunamadı: {missing}")


if __name__ == "__main__":
    unittest.main()
