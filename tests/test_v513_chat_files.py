import engine_source
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChatFileTests(unittest.TestCase):
    def test_live_messages_use_local_time(self):
        # UTC (toISOString) ile eklenen cevaplar sohbette 3 saat yukarıda kalıp görünmüyordu
        ui = (ROOT / "webui" / "nx.js").read_text(encoding="utf-8")
        self.assertNotIn("toISOString().replace('T',' ')", ui)

    def test_doc_actions_do_not_open_hidden_dialog(self):
        src = engine_source.source()
        self.assertIn("def _resolve_doc", src)
        self.assertIn("def _summarize_chat", src)
        self.assertNotIn("path = docs.choose_document()", src)


if __name__ == "__main__":
    unittest.main()
