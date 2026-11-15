"""PR7 Closeout-B3c-1: files.read -> Core doc_summary from a Brain-resolved file, end to end."""
from modules import core_brain_adapter
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_core_map, brain_entry, brain_precedence, brain_understanding, engine_runtime, nxapi, requests_state
from modules.brain_contracts import ContextReference


def file_ref(path, owner=fx.OWNER):
    return ContextReference(id=str(path), kind="file", source="nxapi.file_inventory", owner=owner,
                            provenance={"inventory_scope": "global_pc", "path": str(path), "name": Path(path).name})


class UnderstandingTests(unittest.TestCase):
    def understand(self, text, refs):
        return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                              candidates=tuple(refs), references=tuple(refs))

    def test_single_resolved_file_gives_summarize_operation_and_path(self):
        result = self.understand("rapor.txt dosyasını özetle", [file_ref("/data/rapor.txt")])
        self.assertEqual(result.capability_hint, "files.read")
        self.assertEqual(result.arguments["operation"], "summarize")
        self.assertEqual(result.arguments["path"], "/data/rapor.txt")

    def test_no_reference_proposes_no_target(self):
        result = self.understand("dosyay\u0131 \u00f6zetle", [])
        self.assertNotIn("operation", result.arguments)
        self.assertNotIn("path", result.arguments)

    def test_show_single_resolved_file_is_locate(self):
        result = self.understand("dosyay\u0131 g\u00f6ster", [file_ref("/data/a.pdf")])
        self.assertEqual(result.arguments.get("operation"), "locate")
        self.assertEqual(result.arguments.get("path"), "/data/a.pdf")

    def test_path_never_comes_from_raw_text(self):
        result = self.understand("C:/Windows/system.ini dosyasını özetle", [])
        self.assertNotIn("path", result.arguments)


class CoreValidationTests(unittest.TestCase):
    def test_core_revalidates_path(self):
        with tempfile.TemporaryDirectory() as root:
            good = Path(root) / "a.txt"
            good.write_text("x")
            with patch.object(nxapi, "_roots", return_value=[Path(root)]):
                plan = brain_core_map.core_plan("files.read", {"operation": "summarize", "path": str(good)})
                self.assertEqual(plan, ("file_action", {"operation": "summarize", "path": str(good)}))
                for bad in ({"operation": "summarize", "path": str(Path(root) / "yok.txt")},
                            {"operation": "summarize", "path": "/etc/passwd"},
                            {"operation": "summarize", "path": "a.txt"},
                            {"operation": "delete", "path": str(good)},
                            {"operation": "summarize"}):
                    self.assertIsNone(brain_core_map.core_plan("files.read", bad), bad)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)
        self.file = Path(self.temp.name) / "rapor.txt"
        self.file.write_text("içerik")
        original = brain_entry.build_candidates
        self.rows = [{"path": str(self.file), "name": "rapor.txt", "ext": ".txt"}]
        patcher = patch.object(brain_entry, "build_candidates",
                               lambda **kw: original(**{**kw, "file_reader": lambda *, limit: self.rows[:limit]}))
        patcher.start()
        self.addCleanup(patcher.stop)
        roots = patch.object(nxapi, "_roots", return_value=[Path(self.temp.name)])
        roots.start()
        self.addCleanup(roots.stop)

    def through_brain(self, text, handler=None):
        rid = "b3c1-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = handler or Mock(wraps=self.ctx.handle)
            out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handle, text)
        return entry, out, handle

    def test_summarize_resolved_file_runs_doc_summary_with_that_exact_path(self):
        with patch("modules.engine_intents.dispatch", return_value="ÖZET") as dispatch, \
             patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle = self.through_brain("rapor.txt dosyasını özetle")
        self.assertEqual(out, "ÖZET")
        self.assertEqual(entry.understanding.arguments.get("path"), str(self.file))
        self.assertEqual(dispatch.call_args[0][1], "file_action")
        self.assertEqual(dispatch.call_args[0][2], {"operation": "summarize", "path": str(self.file)})
        self.assertFalse(handle.called)

    def test_summary_uses_brain_path_without_legacy_resolve_doc(self):
        self.ctx.docs = Mock(summarize=Mock(return_value="\u00d6ZET"))
        with patch.object(self.ctx, "_resolve_doc", side_effect=AssertionError("canonical file target cannot be reselected"), create=True), \
             patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle = self.through_brain("rapor.txt dosyas\u0131n\u0131 \u00f6zetle")
        self.assertEqual(out, "\u00d6ZET\n\nDosya olarak almak istersen \u00e7\u0131kt\u0131 al de.")
        self.ctx.docs.summarize.assert_called_once()
        actual = Path(self.ctx.docs.summarize.call_args.args[0]).resolve()
        self.assertEqual(actual, self.file.resolve())
        self.assertFalse(handle.called)

    def test_unquoted_file_request_uses_core_without_legacy_file_gate(self):
        # A validated natural-language file target is not an exact UI file
        # command. The raw file gate's Workbench followup may not override it.
        # Exact quoted-path UI priority is guarded separately in
        # test_brain_notes_final_authority.
        with patch("modules.engine_intents.dispatch", return_value="ÖZET") as dispatch, \
             patch.object(self.ctx, "_file_command",
                          side_effect=AssertionError("raw file gate ran"), create=True) as raw:
            entry, out, handle = self.through_brain("rapor.txt dosyasını özetle")
        self.assertEqual(out, "ÖZET")
        self.assertEqual(brain_entry.core_plan(entry), (
            "file_action", {"operation": "summarize", "path": str(self.file)},
        ))
        self.assertEqual(dispatch.call_args.args[1], "file_action")
        raw.assert_not_called()
        self.assertFalse(handle.called)

    def test_summary_without_candidate_asks_and_never_guesses(self):
        self.rows = []
        with patch("modules.engine_intents.dispatch", side_effect=AssertionError("dispatch yok")), \
             patch.object(self.ctx, "_resolve_doc", side_effect=AssertionError("_resolve_doc tahmin etmemeli"), create=True):
            entry, out, handle = self.through_brain("dosyayı özetle")
        self.assertIn("Hangi dosyayı", out)
        self.assertFalse(handle.called)
        self.assertTrue(entry.understanding.needs_input)

    def test_summary_with_many_candidates_asks(self):
        other = Path(self.temp.name) / "rapor.md"
        other.write_text("y")
        self.rows = [{"path": str(self.file), "name": "rapor.txt"}, {"path": str(other), "name": "rapor.md"}]
        with patch("modules.engine_intents.dispatch", side_effect=AssertionError("dispatch yok")):
            entry, out, handle = self.through_brain("rapor dosyasını özetle")
        self.assertTrue(entry.understanding.needs_input)
        self.assertFalse(handle.called)

    def test_resolved_file_outside_allowed_roots_is_refused_honestly(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "gizli.txt"
            secret.write_text("x")
            self.rows = [{"path": str(secret), "name": "gizli.txt"}]
            with patch("modules.engine_intents.dispatch", side_effect=AssertionError("dispatch yok")):
                rid = "b3c1-" + uuid.uuid4().hex[:8]
                requests_state.register(self.owner, rid)
                with requests_state.activate(self.owner, rid):
                    entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text="gizli.txt dosyasını özetle", source="yazı")
                    handle = Mock()
                    out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handle, "gizli.txt dosyasını özetle")
        self.assertIn("erişemiyorum", out)
        self.assertEqual((feedback.result_status, feedback.reason_code), ("failed", "FILE_TARGET_NOT_ACCESSIBLE"))
        handle.assert_not_called()

    def test_symlink_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "gizli.txt"
            secret.write_text("x")
            link = Path(self.temp.name) / "kisayol.txt"
            try:
                link.symlink_to(secret)
            except (OSError, NotImplementedError):
                self.skipTest("symlink oluşturulamıyor")
            self.rows = [{"path": str(link), "name": "kisayol.txt"}]
            rid = "b3c1-" + uuid.uuid4().hex[:8]
            requests_state.register(self.owner, rid)
            with patch("modules.engine_intents.dispatch", side_effect=AssertionError("dispatch yok")):
                with requests_state.activate(self.owner, rid):
                    entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text="kisayol.txt dosyasını özetle", source="yazı")
                    handle = Mock()
                    out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handle, "kisayol.txt dosyasını özetle")
        self.assertIn("erişemiyorum", out)
        self.assertEqual(feedback.result_status, "failed")
        handle.assert_not_called()

    def test_compound_request_is_not_planned_as_a_single_summary(self):
        for text in ("rapor.txt dosyasını özetle ve çevir", "rapor.txt dosyasını özetle ve kaydet"):
            with self.subTest(text=text), patch("modules.engine_intents.dispatch", return_value="X") as dispatch, \
                    patch.object(brain_precedence, "claim", return_value=None):
                entry, out, handle = self.through_brain(text, handler=Mock(return_value="LEGACY"))
            self.assertNotIn("operation", entry.understanding.arguments)
            self.assertEqual(out, "LEGACY")   # whole sentence goes to the legacy owner; no half is dropped by Core
            self.assertFalse(any(call[0][1] == "file_action" for call in dispatch.call_args_list), text)


if __name__ == "__main__":
    unittest.main()
