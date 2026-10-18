"""RTF, ODT ve JSON dosyaları ek paket olmadan okunur (18 Ekim 2026)."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from modules import docs, kb


def _write(name, data):
    p = Path(tempfile.mkdtemp()) / name
    p.write_bytes(data) if isinstance(data, bytes) else p.write_text(data, encoding="utf-8")
    return str(p)


class ExtraFormatTests(unittest.TestCase):
    def test_json_is_readable_with_turkish_text(self):
        path = _write("a.json", json.dumps({"ad": "Şükrü", "liste": [1, 2]}, ensure_ascii=False))
        text = docs.read_document(path)
        self.assertIn("Şükrü", text)
        self.assertIn("liste", text)

    def test_invalid_json_falls_back_to_plain_text(self):
        self.assertIn("yarım", docs.read_document(_write("b.json", "{ yarım")))

    def test_rtf_text_turkish_escapes_and_no_control_words(self):
        rtf = (r"{\rtf1\ansi\ansicpg1254{\fonttbl{\f0 Arial;}}{\*\generator x;}\pard "
               r"G\'fcn\'fcn raporu: \u351?ehir \b kal\'fdn\b0\par ikinci sat\'fdr}")
        text = docs.read_document(_write("c.rtf", rtf.encode("cp1254")))
        self.assertIn("Günün raporu", text)
        self.assertIn("şehir", text)
        self.assertIn("ikinci satır", text)
        self.assertNotIn("fonttbl", text)
        self.assertNotIn("\\", text)

    def test_odt_text_is_read(self):
        content = ('<?xml version="1.0"?><office:document-content xmlns:office="o" xmlns:text="t">'
                   '<office:body><office:text><text:h>Başlık</text:h><text:p>Birinci</text:p>'
                   '<text:p>İkinci <text:span>vurgu</text:span></text:p></office:text></office:body>'
                   '</office:document-content>')
        path = Path(tempfile.mkdtemp()) / "d.odt"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
            z.writestr("content.xml", content)
        text = docs.read_document(str(path))
        for part in ("Başlık", "Birinci", "İkinci vurgu"):
            self.assertIn(part, text)

    def test_broken_odt_gives_clear_error(self):
        with self.assertRaises(ValueError):
            docs.read_document(_write("e.odt", b"zip degil"))

    def test_formats_are_listed_everywhere(self):
        for ext in (".rtf", ".odt", ".json"):
            self.assertIn(ext, docs.SUPPORTED)
            self.assertIn(ext, kb.INDEXABLE)


if __name__ == "__main__":
    unittest.main()
