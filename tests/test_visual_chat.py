"""visual_chat: sohbetten tetiklenen görsel komutlarının pending-soru akışı.

Gerçek ağa/modele çıkmaz; `visual_commands.create_visual` sahte bir
sonuçla değiştirilir (`patch`).
"""
import unittest
from unittest.mock import patch

from modules import visual_chat
from modules.command_manager import CommandContext
from modules.session_state import SessionState
from modules.image_gen import ImageGenError
from modules.visual_commands import VisualResult


class _Profile:
    slug = "hamdi"


def _ctx(session=None, history=None):
    history = history if history is not None else []
    return CommandContext(
        profile=_Profile(), session=session or SessionState(), emit=lambda *a, **k: None,
        table_chat=lambda: None, history_read=lambda owner, q, limit: history,
        translate=lambda t, target: t, study_intent=lambda t: None,
    )


class TriggerTests(unittest.TestCase):
    def test_keyword_trigger_asks_source_and_sets_pending(self):
        ctx = _ctx()
        reply = visual_chat.handle(ctx, "zihin haritası çizer misin", "zihin haritası çizer misin")
        self.assertIn("sohbetten mi, dosyadan mı", reply)
        self.assertEqual(ctx.session.pending_visual["kind"], "mindmap")
        self.assertEqual(ctx.session.pending_visual["stage"], "source")

    def test_unrelated_sentence_returns_none(self):
        ctx = _ctx()
        self.assertIsNone(visual_chat.handle(ctx, "yarın hava nasıl olacak", "yarın hava nasıl olacak"))
        self.assertIsNone(ctx.session.pending_visual)


class SourceAnswerTests(unittest.TestCase):
    def _pending(self, kind="mindmap", text="zihin haritası çizer misin"):
        session = SessionState()
        session.pending_visual = {"text": text, "kind": kind, "stage": "source"}
        return session

    def test_sohbet_reply_uses_history_and_clears_pending(self):
        session = self._pending()
        ctx = _ctx(session, history=[{"text": "A adımı"}, {"text": "B adımı"}])
        fake = VisualResult(kind="mindmap", label="zihin haritası", path="/x/mindmap_1.png")
        with patch("modules.visual_commands.create_visual", return_value=fake) as gen:
            reply = visual_chat.handle(ctx, "sohbetten", "sohbetten")
        self.assertIn("/x/mindmap_1.png", reply)
        self.assertIsNone(ctx.session.pending_visual)
        self.assertEqual(ctx.session.last_visual["kind"], "mindmap")
        gen.assert_called_once()
        self.assertIn("A adımı", gen.call_args.args[1])

    def test_dosya_reply_redirects_without_network_call(self):
        session = self._pending()
        ctx = _ctx(session)
        with patch("modules.visual_commands.create_visual") as gen:
            reply = visual_chat.handle(ctx, "dosyadan olsun", "dosyadan olsun")
        self.assertIn("Dosyalar sayfasında", reply)
        self.assertIsNone(ctx.session.pending_visual)
        gen.assert_not_called()

    def test_unrecognized_reply_reasks_and_keeps_pending(self):
        session = self._pending()
        ctx = _ctx(session)
        reply = visual_chat.handle(ctx, "bilmiyorum", "bilmiyorum")
        self.assertIn("sohbet", reply.lower())
        self.assertIn("dosya", reply.lower())
        self.assertIsNotNone(ctx.session.pending_visual)

    def test_empty_history_reports_no_content_without_network_call(self):
        session = self._pending()
        ctx = _ctx(session, history=[])
        with patch("modules.visual_commands.create_visual") as gen:
            reply = visual_chat.handle(ctx, "sohbetten", "sohbetten")
        self.assertIn("içerik bulamadım", reply)
        gen.assert_not_called()


class RetryTests(unittest.TestCase):
    def test_retry_without_last_visual_falls_through(self):
        ctx = _ctx()
        self.assertIsNone(visual_chat.handle(ctx, "yeniden dene", "yeniden dene"))

    def test_retry_regenerates_with_same_content_and_kind(self):
        session = SessionState()
        session.last_visual = {"text": "x", "content": "A, B, C", "kind": "flowchart"}
        ctx = _ctx(session)
        fake = VisualResult(kind="flowchart", label="akış şeması", path="/x/flowchart_2.png")
        with patch("modules.visual_commands.create_visual", return_value=fake) as gen:
            reply = visual_chat.handle(ctx, "yeniden dene", "yeniden dene")
        self.assertIn("/x/flowchart_2.png", reply)
        gen.assert_called_once_with("x", "A, B, C", slug="hamdi", kind="flowchart")


class ErrorHandlingTests(unittest.TestCase):
    def test_image_gen_error_reported_without_crashing(self):
        session = SessionState()
        session.pending_visual = {"text": "x", "kind": "mindmap", "stage": "source"}
        ctx = _ctx(session, history=[{"text": "A adımı"}])
        with patch("modules.visual_commands.create_visual", side_effect=ImageGenError("x", "NO_KEY")):
            reply = visual_chat.handle(ctx, "sohbetten", "sohbetten")
        self.assertIn("NO_KEY", reply)

    def test_value_error_reported_without_crashing(self):
        session = SessionState()
        session.pending_visual = {"text": "x", "kind": "mindmap", "stage": "source"}
        ctx = _ctx(session, history=[{"text": "A adımı"}])
        with patch("modules.visual_commands.create_visual", side_effect=ValueError("boş içerik")):
            reply = visual_chat.handle(ctx, "sohbetten", "sohbetten")
        self.assertEqual(reply, "boş içerik")


if __name__ == "__main__":
    unittest.main()


class FileButtonGorsellestirTests(unittest.TestCase):
    """Dosyalar ekranındaki 'Görselleştir' düğmesi -> _file_command. Bu akışta
    içerik otomatik (dosya özetinden) alınır, sohbet/dosya sorusu sorulmaz."""

    def _runtime(self, summarize_result="A, B, C adımları"):
        import re
        from types import SimpleNamespace
        from unittest.mock import Mock
        from modules import translate as tr
        session = SessionState()
        source = Mock()
        source.is_file.return_value = True
        source.is_dir.return_value = False
        source.__str__ = Mock(return_value="rapor.docx")
        runtime = SimpleNamespace(
            _FILE_CMD=re.compile(r'^((?:"[^"]{4,400}"\s+){1,10})(.+)$'), _tr_lower=str.lower,
            _IMG_EXT=(".png",), re=re, tr=tr,
            profile=_Profile(), _session=lambda: session,
            docs=SimpleNamespace(summarize=Mock(return_value=summarize_result)),
        )
        return runtime, source

    def test_gorsellestir_action_generates_from_file_summary(self):
        from modules.main_documents import _file_command
        from modules import nxapi
        runtime, source = self._runtime()
        fake = VisualResult(kind="visualize", label="görsel özet", path="/x/visualize_1.png")
        with patch.object(nxapi, "allowed", return_value=source), \
             patch("modules.visual_commands.create_visual", return_value=fake) as gen:
            reply = _file_command(runtime, '"rapor.docx" dosyasını görselleştir')
        self.assertIn("/x/visualize_1.png", reply)
        gen.assert_called_once_with("dosyasını görselleştir", "A, B, C adımları", slug="hamdi", kind="visualize")
        self.assertEqual(runtime._session().last_visual["kind"], "visualize")

    def test_gorsellestir_honors_explicit_type_word(self):
        from modules.main_documents import _file_command
        from modules import nxapi
        runtime, source = self._runtime()
        fake = VisualResult(kind="timeline", label="zaman çizelgesi", path="/x/timeline_1.png")
        with patch.object(nxapi, "allowed", return_value=source), \
             patch("modules.visual_commands.create_visual", return_value=fake) as gen:
            _file_command(runtime, '"rapor.docx" dosyasını zaman çizelgesi olarak görselleştir')
        self.assertEqual(gen.call_args.kwargs["kind"], "timeline")
