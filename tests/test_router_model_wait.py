"""Legacy route turn'ünün beklemeye ait sözleşmeleri: kapı kaldırıldı, garantiler taşındı.

Eski `engine_tools.route` modeli beklerken oturum durumunu tüketirdi. Canonical karar
(model-free Understanding) beklemeye girmediği için bir geç yanıt artık karar aşamasında
bekleyen isteği yiyemez; korunan sözleşme budur, model beklemesi yürütücüde kalır.
"""
import inspect
import unittest
from unittest.mock import patch

from modules import brain_gates, brain_understanding, engine_runtime, llm
from modules.brain_contracts import ActiveContext

OWNER, RID = "hamdi", "rid-wait"


def understand(text: str):
    return brain_understanding.understand(owner=OWNER, request_id=RID, text=text,
                                          active_context=ActiveContext(owner=OWNER, request_id=RID),
                                          candidates=(), references=())


class RetiredRouteWaitTests(unittest.TestCase):
    def test_the_engine_exports_no_route_door_to_wait_on(self):
        self.assertNotIn("route", engine_runtime._HANDLERS["engine_tools"])
        self.assertNotIn("intent_router", engine_runtime._DEPENDENCIES)

    def test_the_canonical_decision_never_waits_on_a_model(self):
        def no_provider(*_a, **_k):
            raise AssertionError("canonical karar modeli beklememeli")
        texts = ("merhaba", "bu konuşmayı özetle", "ekranı analiz et", "Açık pencereleri listele",
                 "İstanbul son haberler neler?", "yarın 10'da ilaç hatırlat", "rapor.txt dosyasını özetle",
                 "Chrome penceresini öne getir")
        with patch.object(llm, "ask", no_provider), patch.object(llm, "chat", no_provider):
            for text in texts:
                with self.subTest(text=text):
                    self.assertIsNotNone(understand(text).request_kind, text)

    def test_no_semantic_door_clears_the_pending_request_slot(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "modules"
        for name in ("brain_entry", "brain_gates", "brain_understanding", "command_manager", "engine_tools"):
            with self.subTest(module=name):
                text = (root / f"{name}.py").read_text(encoding="utf-8")
                self.assertNotIn(".pending_request = None", text, name)

    def test_the_pending_request_is_a_bounded_state_key(self):
        # Bekleyen isteğin tek sahibi exact state gate; oradan geçen cümle modele düşmez.
        self.assertIn("pending_request", brain_gates._PENDING_SESSION_IDS)
        self.assertTrue(callable(brain_gates.exact_state_gate))

    def test_route_projection_is_the_only_legacy_shaped_door(self):
        from modules import brain_entry
        body = inspect.getsource(brain_entry.route_command)
        self.assertIn("nested_step(command, runtime)", body)
        self.assertNotIn("classify", body)


if __name__ == "__main__":
    unittest.main()
