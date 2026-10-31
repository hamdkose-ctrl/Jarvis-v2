from __future__ import annotations

import time
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from modules import brain_entry, nxapi
from modules.brain_contracts import ActiveContext, ContextReference, RequestKind

OWNER = "hamdi"
RID = "req-production-performance"


@contextmanager
def _file_cache(rows, ts):
    with nxapi._FILE_CACHE_LOCK:
        old_rows = nxapi._FILE_CACHE["rows"]
        old_ts = nxapi._FILE_CACHE["ts"]
        nxapi._FILE_CACHE["rows"] = rows
        nxapi._FILE_CACHE["ts"] = ts
    try:
        yield
    finally:
        with nxapi._FILE_CACHE_LOCK:
            nxapi._FILE_CACHE["rows"] = old_rows
            nxapi._FILE_CACHE["ts"] = old_ts


def _runtime(*, tasks=None):
    return SimpleNamespace(
        profile=SimpleNamespace(
            slug=OWNER,
            name="Hamdi",
            data={"tasks": list(tasks or ()), "items": [], "events": []},
        ),
        _sessions=object(),
        flags={"sleep": False},
        _pending_photo={},
    )


def _context(*, recent=()):
    return ActiveContext(owner=OWNER, request_id=RID, recent_references=tuple(recent))


def _prepare(text: str, *, runtime=None, active=None):
    runtime = runtime or _runtime()
    active = active or _context()
    with patch.object(brain_entry, "_build_context", return_value=active), \
         patch.object(brain_entry, "_state_refs", return_value=()):
        return brain_entry.prepare(
            runtime,
            owner=OWNER,
            request_id=RID,
            text=text,
            source="yazı",
        )


class BrainProductionEntryPerformanceTests(unittest.TestCase):
    def test_ordinary_chat_cold_cache_does_not_sync_scan_global_files(self):
        with _file_cache(None, 0.0), \
             patch.object(nxapi, "_scan_files", return_value=[]) as scan:
            result = _prepare("selam")
        self.assertEqual(result.understanding.request_kind, RequestKind.CHAT)
        scan.assert_not_called()

    def test_ordinary_chat_stale_cache_does_not_sync_scan_global_files(self):
        stale = [{"path": "C:/tmp/eski.txt", "name": "eski.txt", "mtime": 1.0}]
        with _file_cache(stale, 0.0), \
             patch.object(nxapi, "_scan_files", return_value=[]) as scan:
            result = _prepare("selam")
        self.assertEqual(result.understanding.request_kind, RequestKind.CHAT)
        scan.assert_not_called()

    def test_active_and_profile_candidates_do_not_require_global_file_scan(self):
        live = ContextReference(
            id="active-note",
            kind="note",
            source="active_context",
            owner=OWNER,
            provenance={"text": "Aktif not"},
        )
        runtime = _runtime(tasks=[{"id": 17, "text": "Raporu bitir", "done": False}])
        active = _context(recent=(live,))
        with _file_cache(None, 0.0), \
             patch.object(nxapi, "_scan_files", return_value=[]) as scan:
            result = _prepare("selam", runtime=runtime, active=active)
        ids = {row.id for row in result.candidates}
        self.assertIn("active-note", ids)
        self.assertIn("17", ids)
        scan.assert_not_called()

    def test_explicit_file_request_can_discover_file_candidates_on_cold_cache(self):
        row = {
            "path": "C:/Users/Hamdi/Documents/rapor.docx",
            "name": "rapor.docx",
            "ext": "docx",
            "mtime": 10.0,
        }
        with _file_cache(None, 0.0), \
             patch.object(nxapi, "_scan_files", return_value=[row]) as scan:
            result = _prepare("rapor.docx dosyasını bul")
        scan.assert_called_once_with()
        self.assertEqual(result.understanding.capability_hint, "files.read")
        self.assertTrue(any(ref.kind == "file" and ref.id == row["path"] for ref in result.candidates))
        self.assertTrue(any(ref.kind == "file" and ref.id == row["path"] for ref in result.references))

    def test_fresh_cached_file_inventory_keeps_fast_file_candidate_behavior(self):
        row = {
            "path": "C:/Users/Hamdi/Documents/rapor.docx",
            "name": "rapor.docx",
            "ext": "docx",
            "mtime": 10.0,
        }
        with _file_cache([row], time.monotonic()), \
             patch.object(nxapi, "_scan_files", return_value=[]) as scan:
            result = _prepare("rapor.docx dosyasını bul")
        scan.assert_not_called()
        self.assertTrue(any(ref.kind == "file" and ref.id == row["path"] for ref in result.candidates))
        self.assertTrue(any(ref.kind == "file" and ref.id == row["path"] for ref in result.references))


if __name__ == "__main__":
    unittest.main()
