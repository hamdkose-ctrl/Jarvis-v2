"""Sohbetteki adresler tıklanabilir olmalı.

Kullanıcı geri bildirimi (22 Kasım 2026): "kaynaklar tıklanacak şekilde olursa
tamamdır". Akademik listede her kaydın adresi düz metin olarak yazılıyordu.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "webui" / "nx.js"


class ClickableSourceLinksTests(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8")

    def test_urls_become_links_in_chat_text(self):
        self.assertIn('target="_blank"', self.text)
        self.assertIn('rel="noopener noreferrer"', self.text)
        self.assertIn("https?:\/\/", self.text)      # yalnız http(s) adresler bağlanır

    def test_only_http_schemes_are_linked(self):
        # javascript:/data: gibi şemalar bağlanmaz; desende yalnız https? var.
        body = self.text[self.text.index("function inl(s){"):]
        body = body[:body.index("'<b>$1</b>'")]
        self.assertIn("https?:\/\/", body)
        self.assertNotIn("javascript:", body)

    def test_linkify_runs_before_bold_rewrite(self):
        body = self.text[self.text.index("function inl(s){"):]
        body = body[:body.index("\n}")]
        self.assertLess(body.index("target="), body.index("'<b>$1</b>'"))
