"""One suite run per machine: the lock, the stale reclaim and the PASS cache.

Issue 679 came from two independent callers reaching the full release suite on the
same PC at the same time (the updater installing a version and the PC acceptance
watcher testing an open PR). These tests pin the three boundaries that keep the
suite honest without weakening it.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import validation_lock


class SingleRunTests(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.root = Path(self._folder.name) / "jarvis-data"
        self.root.mkdir()
        patcher = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_caller_gets_no_verdict_instead_of_a_race(self):
        with validation_lock.only_one_run("first") as owned:
            self.assertTrue(owned)
            with validation_lock.only_one_run("second", wait_seconds=0) as also_owned:
                self.assertFalse(also_owned)

    def test_released_claim_lets_the_next_caller_run(self):
        with validation_lock.only_one_run("first") as owned:
            self.assertTrue(owned)
        with validation_lock.only_one_run("second", wait_seconds=0) as owned:
            self.assertTrue(owned)

    def test_claim_of_a_dead_process_is_reclaimed(self):
        # A crashed run must not block every later acceptance run forever.
        (self.root / validation_lock.LOCK_NAME).write_text(
            json.dumps({"pid": 999999999, "owner": "crashed", "at": time.time()}),
            encoding="utf-8")
        with validation_lock.only_one_run("later", wait_seconds=0) as owned:
            self.assertTrue(owned)

    def test_claim_held_by_a_live_process_is_not_stolen(self):
        (self.root / validation_lock.LOCK_NAME).write_text(
            json.dumps({"pid": os.getpid(), "owner": "live", "at": time.time()}),
            encoding="utf-8")
        with validation_lock.only_one_run("other", wait_seconds=0) as owned:
            self.assertFalse(owned)

    def test_only_a_pass_is_remembered(self):
        key = "a" * 64
        validation_lock.remember_verdict(key, False, "kırmızı")
        self.assertIsNone(validation_lock.cached_verdict(key))
        validation_lock.remember_verdict(key, True, "yeşil")
        self.assertIn("yeşil", validation_lock.cached_verdict(key) or "")

    def test_tree_digest_changes_with_any_source_byte(self):
        project = Path(self._folder.name) / "project"
        (project / "modules").mkdir(parents=True)
        source = project / "modules" / "x.py"
        source.write_text("A = 1\n", encoding="utf-8")
        before = validation_lock.tree_digest(project, "python")
        source.write_text("A = 2\n", encoding="utf-8")
        self.assertNotEqual(before, validation_lock.tree_digest(project, "python"))

    def test_tree_digest_binds_the_interpreter(self):
        project = Path(self._folder.name) / "project"
        project.mkdir()
        (project / "x.py").write_text("A = 1\n", encoding="utf-8")
        self.assertNotEqual(validation_lock.tree_digest(project, "py-a"),
                            validation_lock.tree_digest(project, "py-b"))


class CachedSuiteTests(unittest.TestCase):
    """The suite itself must honour the cache and never invent a verdict."""

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.root = Path(self._folder.name) / "jarvis-data"
        self.root.mkdir()
        patcher = patch.dict(os.environ, {"JARVIS_DATA_DIR": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_remembered_pass_skips_the_identical_exam(self):
        from modules import validation
        project = Path(self._folder.name) / "project"
        (project / "tests").mkdir(parents=True)
        (project / "tests" / "x.py").write_text("A = 1\n", encoding="utf-8")
        key = validation_lock.tree_digest(project, str(sys_executable()))
        validation_lock.remember_verdict(key, True, "önceki yeşil koşum")
        ok, log = validation.run_checks(project)
        self.assertTrue(ok)
        self.assertIn("önceki yeşil koşum", log)
        self.assertIn("sınav tekrarlanmadı", log)

    def test_busy_machine_reports_no_verdict_not_a_failure(self):
        from modules import validation
        project = Path(self._folder.name) / "project"
        (project / "tests").mkdir(parents=True)
        for name in list(validation.JS_GROUPS):
            (project / "tests" / (name + ".js")).write_text("//\n", encoding="utf-8")
        for name in list(validation.SMOKE_GROUPS):
            (project / "tests" / (name + ".py")).write_text("\n", encoding="utf-8")
        (project / "webui").mkdir()
        (self.root / validation_lock.LOCK_NAME).write_text(
            json.dumps({"pid": os.getpid(), "owner": "live", "at": time.time()}),
            encoding="utf-8")
        from contextlib import contextmanager

        @contextmanager
        def busy(owner, **kwargs):
            yield False

        with patch.object(validation_lock, "only_one_run", busy):
            ok, log = validation.run_checks(project)
        self.assertFalse(ok)
        self.assertIn("INCONCLUSIVE", log)


def sys_executable():
    import sys
    return str(sys.executable)


if __name__ == "__main__":
    unittest.main()
