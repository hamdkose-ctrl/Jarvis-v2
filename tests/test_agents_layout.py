"""AGENTS.md kısa kalır; alan notları docs/agents/ altındadır ve hepsi AGENTS.md'den bağlıdır."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 40_000


class AgentsLayoutTests(unittest.TestCase):
    def test_agents_md_stays_short_and_has_core_sections(self):
        text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertLess(len(text.encode('utf-8')), LIMIT,
                        'AGENTS.md büyüdü; alana özgü ayrıntıyı docs/agents/ altına taşı.')
        for heading in ('## Çalışma kuralları', '## Alan notları', '## Klasör haritası', '## Testler'):
            self.assertIn(heading, text)

    def test_every_area_note_is_linked_and_not_empty(self):
        text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        notes = sorted((ROOT / 'docs' / 'agents').glob('*.md'))
        self.assertTrue(notes)
        for note in notes:
            with self.subTest(note=note.name):
                self.assertIn(f'docs/agents/{note.name}', text, 'Alan notu AGENTS.md dizininde yok.')
                self.assertGreater(len(note.read_text(encoding='utf-8').strip()), 200)


if __name__ == '__main__':
    unittest.main()
