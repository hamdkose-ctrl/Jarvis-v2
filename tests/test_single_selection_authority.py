"""P0-3 temizliği: tek seçim yetkisi Router'da, tek zincir kaydı gizlilik modülünde.

Yol haritası "OpenRouter kalıntıları, çift registry'ler" diyordu. Ölçüm: kodda
OpenRouter referansı yok, `llm._send` artık kendi sağlayıcı seçimini yapmıyor,
zincirler tek yerde. Bu testler geri dönüşü engeller.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

class OpenRouterRemovalTests(unittest.TestCase):
    def test_no_openrouter_reference_in_code_web_or_config(self):
        root = Path(__file__).resolve().parents[1]
        hedefler = list((root / 'modules').glob('*.py')) + list(root.glob('web*.py')) + \
            [root / 'config.py', root / 'gui.py', root / 'main.py'] + \
            list((root / 'webui').glob('*.js'))
        kirli = []
        for path in hedefler:
            if not path.is_file():
                continue
            text = path.read_text(encoding='utf-8', errors='ignore').lower()
            if 'openrouter' in text:
                kirli.append(path.name)
        self.assertEqual(kirli, [])


class SingleAuthorityTests(unittest.TestCase):
    def test_send_goes_through_the_router(self):
        from modules import llm
        with patch('modules.smart_router.run_request', side_effect=RuntimeError('router')) as run:
            with self.assertRaises(RuntimeError):
                llm._send('merhaba', '', 20, None)
        self.assertEqual(run.call_count, 1)

    def test_transport_does_not_select_another_provider(self):
        """`_send_provider` tek sağlayıcı, tek deneme; yedek seçim Router'ın işi."""
        from modules import llm
        source = Path(llm.__file__).read_text(encoding='utf-8')
        govde = source[source.index('def _send_provider('):]
        govde = govde[:govde.index('\ndef ') if '\ndef ' in govde else len(govde)]
        self.assertIn('No cross-provider fallback', govde)
        self.assertNotIn('smart_router', govde)

    def test_one_chain_registry(self):
        from modules import provider_privacy, smart_router
        router = Path(smart_router.__file__).read_text(encoding='utf-8')
        self.assertIn('provider_privacy.CHAINS', router)
        # Zincir sırası ikinci kez yazılmıyor (sağlayıcı *kümesi* yazılabilir, sıra değil).
        self.assertNotIn("'gemini', 'groq', 'cloudflare', 'ollama'", router)
        self.assertNotIn('"gemini", "groq", "cloudflare", "ollama"', router)
        self.assertTrue(provider_privacy.CHAINS)

    def test_private_lanes_stay_local(self):
        from modules import llm
        with self.assertRaises(RuntimeError):
            llm.transcribe(None)                                # ses buluta gitmez
        with patch('modules.llm._backend', return_value='gemini'):
            with self.assertRaises(ValueError):
                llm.embed(['gizli belge'])                      # gömme yalnız yerel
