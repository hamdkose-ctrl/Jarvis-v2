"""AGENTS.md alan notları indeksi docs/agents ile aynı kalır."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_RE = re.compile(r"`(docs/agents/[^`]+\.md)`.*\((\d+) bölüm\)")


def _section_count(path):
    count = 0
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            count += 1
    return count


class AgentsIndexTests(unittest.TestCase):
    def test_agents_index_matches_files_and_section_counts(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        entries = {path: int(count) for path, count in INDEX_RE.findall(agents)}
        listed = set(entries)
        actual = {path.relative_to(ROOT).as_posix() for path in (ROOT / "docs" / "agents").glob("*.md")}

        self.assertEqual(listed, actual, f"AGENTS.md alan listesi uyuşmuyor: eksik={sorted(actual - listed)}, fazla={sorted(listed - actual)}")
        for relpath, declared in entries.items():
            path = ROOT / relpath
            self.assertTrue(path.is_file(), f"AGENTS.md dosyası bulunamadı: {relpath}")
            real = _section_count(path)
            self.assertEqual(
                declared,
                real,
                f"{relpath}: AGENTS.md {declared} bölüm yazıyor, gerçek {real}; yeni bölüm eklersen buradaki sayıyı güncelle",
            )


if __name__ == "__main__":
    unittest.main()
