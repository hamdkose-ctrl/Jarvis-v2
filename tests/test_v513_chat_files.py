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
        # Hedef dosyasız bir istek için gizli dosya seçtirme kutusu açılmaz; konuşma özeti
        # own sohbet geçmişinden, dosya özeti ise Brain'in çözdüğü referanstan yürür.
        src = engine_source.source()
        self.assertNotIn("path = docs.choose_document()", src)
        self.assertIn("def _conversation_summary", src)
        self.assertNotIn("def _resolve_doc", src)

    def test_the_conversation_summary_is_reachable_without_a_file(self):
        from modules import brain_gates
        self.assertTrue(brain_gates.conversation_summary_request("bu konuşmayı özetle"))
        self.assertFalse(brain_gates.conversation_summary_request("rapor.txt dosyasını özetle"))


if __name__ == "__main__":
    unittest.main()
