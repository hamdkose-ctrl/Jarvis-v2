"""Belge okuma süre sınırı klasör analizi bütçesine bağlanır (18 Ekim 2026)."""
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import docs, folder_analysis, kb, nxapi
from tests.test_folder_analysis import Profile


class Done:
    returncode, stdout, stderr = 0, b"metin", b""


class DeadlineTests(unittest.TestCase):
    def _timeout_used(self, func, **kw):
        seen = []

        def fake_run(*a, **k):
            seen.append(k.get("timeout"))
            return Done()
        with patch.object(docs, "markitdown_available", return_value=True), patch.object(subprocess, "run", fake_run):
            func(str(Path(tempfile.mkdtemp()) / "x.pptx"), **kw)
        return seen[0]

    def test_default_timeouts_unchanged(self):
        self.assertEqual(self._timeout_used(docs.read_markitdown_isolated), 300)
        self.assertEqual(self._timeout_used(docs.read_pdf_isolated), 900)

    def test_deadline_shortens_timeout(self):
        t = self._timeout_used(docs.read_markitdown_isolated, deadline=time.monotonic() + 20)
        self.assertLessEqual(t, 20)
        self.assertGreaterEqual(t, 5)
        t = self._timeout_used(docs.read_pdf_isolated, deadline=time.monotonic() + 20)
        self.assertLessEqual(t, 20)

    def test_expired_deadline_keeps_small_floor(self):
        t = self._timeout_used(docs.read_markitdown_isolated, deadline=time.monotonic() - 50)
        self.assertEqual(t, 5)

    def test_folder_analysis_passes_its_deadline(self):
        home = Path(tempfile.mkdtemp())
        folder = home / "Downloads"
        folder.mkdir()
        (folder / "a.txt").write_text("merhaba dünya", encoding="utf-8")
        seen = []
        real = docs.read_document

        def spy(path, **kw):
            seen.append(kw.get("deadline"))
            return real(path, **{k: v for k, v in kw.items() if k != "deadline"})
        with patch.object(docs, "read_document", spy), patch.object(nxapi, "HOME", home), \
                patch.object(nxapi, "known_folder", return_value=None), \
                patch.object(kb, "ROOT", home / "kb"):
            folder_analysis.analyze(Profile(), folder, use_model=False)
        self.assertTrue(seen and seen[0] is not None)


if __name__ == "__main__":
    unittest.main()
