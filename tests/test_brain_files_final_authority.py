"""PR7 Closeout: remaining natural-language file operations use one Brain target and Core action."""
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
    path = str(path)
    return ContextReference(
        id=path,
        kind="file",
        source="nxapi.file_inventory",
        owner=owner,
        provenance={"inventory_scope": "global_pc", "path": path, "name": Path(path).name},
    )


class UnderstandingTests(unittest.TestCase):
    def understand(self, text, refs=()):
        refs = tuple(refs)
        return brain_understanding.understand(
            owner=fx.OWNER,
            request_id=fx.RID,
            text=text,
            active_context=fx.context(),
            candidates=refs,
            references=refs,
        )

    def test_single_file_operations_are_explicit_and_never_take_path_from_raw_text(self):
        ref = file_ref("/data/rapor.txt")
        cases = (
            ("rapor.txt dosyasını özetle", "summarize"),
            ("rapor.txt dosyasını analiz et", "analyze"),
            ("rapor.txt dosyasını aç", "open"),
            ("rapor.txt dosyasını bul", "locate"),
        )
        for text, operation in cases:
            with self.subTest(text=text):
                result = self.understand(text, [ref])
                self.assertEqual(result.capability_hint, "files.read")
                self.assertEqual(result.arguments.get("operation"), operation)
                self.assertEqual(result.arguments.get("path"), "/data/rapor.txt")

        raw_only = self.understand("C:/Windows/system.ini dosyasını analiz et")
        self.assertNotIn("path", raw_only.arguments)

    def test_translate_and_convert_require_bounded_explicit_parameters(self):
        ref = file_ref("/data/rapor.docx")
        translated = self.understand("rapor.docx dosyasını İngilizceye çevir", [ref])
        self.assertEqual(translated.capability_hint, "files.read")
        self.assertEqual(translated.arguments.get("operation"), "translate")
        self.assertEqual(translated.arguments.get("target"), "İngilizce")
        self.assertEqual(translated.arguments.get("path"), "/data/rapor.docx")

        converted = self.understand("rapor.docx dosyasını PDF'e dönüştür", [ref])
        self.assertEqual(converted.capability_hint, "files.read")
        self.assertEqual(converted.arguments.get("operation"), "convert")
        self.assertEqual(converted.arguments.get("format"), "pdf")
        self.assertEqual(converted.arguments.get("path"), "/data/rapor.docx")

        for text in ("rapor.docx dosyasını çevir", "rapor.docx dosyasını dönüştür"):
            with self.subTest(text=text):
                result = self.understand(text, [ref])
                self.assertTrue(result.needs_input)
                self.assertNotIn("path", brain_core_map.core_plan("files.read", result.arguments) or ({}, {})[1])

    def test_compare_uses_only_resolved_file_set_and_list_needs_no_target(self):
        a = file_ref("/data/a.txt")
        b = file_ref("/data/b.txt")
        compared = self.understand("a.txt ve b.txt dosyalarını karşılaştır", [a, b])
        self.assertEqual(compared.capability_hint, "files.read")
        self.assertEqual(compared.arguments.get("operation"), "compare")
        self.assertEqual(compared.arguments.get("paths"), ("/data/a.txt", "/data/b.txt"))

        listed = self.understand("dosyalarımı listele")
        self.assertEqual(listed.capability_hint, "files.read")
        self.assertEqual(listed.arguments.get("operation"), "list")
        self.assertNotIn("path", listed.arguments)
        self.assertNotIn("paths", listed.arguments)


class CoreValidationTests(unittest.TestCase):
    def test_core_validates_operation_and_exact_paths(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            a, b = root / "a.txt", root / "b.txt"
            a.write_text("a", encoding="utf-8")
            b.write_text("b", encoding="utf-8")
            with patch.object(nxapi, "_roots", return_value=[root]):
                expected = {
                    "summarize": {"operation": "summarize", "path": str(a)},
                    "analyze": {"operation": "analyze", "path": str(a)},
                    "open": {"operation": "open", "path": str(a)},
                    "locate": {"operation": "locate", "path": str(a)},
                    "translate": {"operation": "translate", "path": str(a), "target": "İngilizce"},
                    "convert": {"operation": "convert", "path": str(a), "format": "pdf"},
                    "compare": {"operation": "compare", "paths": (str(a), str(b))},
                    "list": {"operation": "list"},
                }
                for operation, args in expected.items():
                    with self.subTest(operation=operation):
                        self.assertEqual(brain_core_map.core_plan("files.read", args), ("file_action", args))

                self.assertIsNone(brain_core_map.core_plan("files.read", {"operation": "open", "path": str(root / "missing.txt")}))
                self.assertIsNone(brain_core_map.core_plan("files.read", {"operation": "convert", "path": str(a), "format": "exe"}))
                self.assertIsNone(brain_core_map.core_plan("files.read", {"operation": "compare", "paths": (str(a), "/etc/passwd")}))


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
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
        self.file.write_text("içerik", encoding="utf-8")
        original = brain_entry.build_candidates
        rows = [{"path": str(self.file), "name": "rapor.txt", "ext": ".txt"}]
        candidate_patch = patch.object(
            brain_entry,
            "build_candidates",
            lambda **kw: original(**{**kw, "file_reader": lambda *, limit: rows[:limit]}),
        )
        candidate_patch.start()
        self.addCleanup(candidate_patch.stop)
        roots = patch.object(nxapi, "_roots", return_value=[Path(self.temp.name)])
        roots.start()
        self.addCleanup(roots.stop)

    def through_brain(self, text, handler=None):
        rid = "file-final-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = handler or Mock(return_value="LEGACY")
            out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handle, text)
        return entry, out, feedback, handle

    def test_canonical_analyze_dispatches_exact_target_without_legacy_resolve_doc(self):
        with patch.object(self.ctx, "_resolve_doc", side_effect=AssertionError("canonical file path must not be reselected"), create=True), \
             patch.object(brain_precedence, "claim", return_value=None), \
             patch("modules.engine_intents.dispatch", return_value="ANALİZ") as dispatch:
            entry, out, feedback, handle = self.through_brain("rapor.txt dosyasını analiz et")
        self.assertEqual(out, "ANALİZ")
        self.assertEqual(feedback.result_status, "handled")
        self.assertEqual(entry.understanding.arguments.get("path"), str(self.file))
        self.assertEqual(dispatch.call_args[0][1], "file_action")
        self.assertEqual(dispatch.call_args[0][2], {"operation": "analyze", "path": str(self.file)})
        handle.assert_not_called()

    def test_exact_quoted_ui_file_command_still_beats_canonical_plan(self):
        text = f'"{self.file}" dosyasını özetle'
        with patch.object(self.ctx, "_file_command", return_value="DÜĞME", create=True), \
             patch("modules.engine_intents.dispatch", return_value="CORE") as dispatch:
            _entry, out, _feedback, _handle = self.through_brain(text)
        self.assertEqual(out, "DÜĞME")
        dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
