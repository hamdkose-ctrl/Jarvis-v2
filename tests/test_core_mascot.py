"""Çekirdek maskotu: klipler gerçek, bütçede ve arayüze bağlı (T4-maskot)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'webui'
MASCOT = WEB / 'mascot'
CLIP_BUDGET = 380 * 1024
TOTAL_BUDGET = 1800 * 1024
STATES = {'idle', 'listening', 'thinking', 'working', 'speaking'}


def mapping() -> dict[str, str]:
    """mascot.js içindeki durum → klip tablosunu okur (tek kaynak)."""
    source = (WEB / 'mascot.js').read_text(encoding='utf-8')
    block = source[source.index('CLIPS = Object.freeze('):]
    block = block[:block.index('});')]
    return dict(re.findall(r"(\w+):\s*'([a-z0-9_]+)'", block))


class MascotAssetTests(unittest.TestCase):
    def test_every_orb_state_maps_to_an_existing_clip(self):
        table = mapping()
        self.assertEqual(set(table), STATES)
        for state, name in table.items():
            with self.subTest(state=state):
                path = MASCOT / (name + '.webp')
                self.assertTrue(path.is_file(), f'{state} → {path.name} yok')
                head = path.read_bytes()[:12]
                self.assertEqual(head[:4], b'RIFF')
                self.assertEqual(head[8:12], b'WEBP')

    def test_clips_stay_inside_the_download_budget(self):
        total = 0
        for path in sorted(MASCOT.glob('*.webp')):
            with self.subTest(clip=path.name):
                self.assertLessEqual(path.stat().st_size, CLIP_BUDGET)
            total += path.stat().st_size
        still = MASCOT / 'bosta_still.png'
        self.assertTrue(still.is_file(), 'hareket azaltma için tek kare yok')
        total += still.stat().st_size
        self.assertLessEqual(total, TOTAL_BUDGET)

    def test_command_center_loads_the_mascot_before_nx(self):
        html = (WEB / 'nx.html').read_text(encoding='utf-8')
        self.assertIn('/mascot.js', html)
        self.assertLess(html.index('/mascot.js'), html.index('/nx.js'))

    def test_reactor_carries_the_mascot_slot_and_hides_it_for_live_preview(self):
        console = (WEB / 'home-console.js').read_text(encoding='utf-8')
        self.assertIn('class="mascot"', console)
        self.assertIn('mascot.hidden = valid', console)

    def test_orb_changes_reach_the_mascot(self):
        nx = (WEB / 'nx.js').read_text(encoding='utf-8')
        self.assertGreaterEqual(nx.count('Mascot?.set(S.orb)'), 3)

    def test_module_never_reaches_the_network(self):
        source = (WEB / 'mascot.js').read_text(encoding='utf-8')
        self.assertNotIn('http://', source)
        self.assertNotIn('https://', source)


if __name__ == '__main__':
    unittest.main()
