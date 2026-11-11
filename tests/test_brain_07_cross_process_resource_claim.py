"""BRAIN-07: live OS file claims across separate Windows/Unix processes.

No model, network or external application. Verifies that the only existing
in-process scheduler's tickets also receive a real OS-level collision fence.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from modules import resource_leases


_SCRIPT = """
import sys
from pathlib import Path
from modules.resource_leases import LeaseConflict, process_resource_claim
try:
    with process_resource_claim(Path(sys.argv[1]), sys.argv[2]):
        pass
except LeaseConflict:
    sys.exit(19)
"""


class CrossProcessReadOnlyResourceClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner_root = Path(self.tmp.name)
        self.repo_root = Path(__file__).resolve().parents[1]

    def child_claim(self, key: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", _SCRIPT, str(self.owner_root), key],
            cwd=self.repo_root, capture_output=True, text=True, timeout=20,
        )

    def test_live_resource_rejects_other_process_and_releases(self):
        for key in (
            resource_leases.resource_key("gmail_account", "alice-account"),
            resource_leases.resource_key("command", "a" * 64),
        ):
            with self.subTest(key=key):
                with resource_leases.process_resource_claim(
                    self.owner_root, key,
                ):
                    other = self.child_claim(key)
                    self.assertEqual(
                        other.returncode, 19,
                        f"Unexpected competing resource result: {other.stderr}",
                    )
                freed = self.child_claim(key)
                self.assertEqual(
                    freed.returncode, 0,
                    f"OS claim was not released: {freed.stderr}",
                )

    def test_distinct_resource_keys_remain_independent(self):
        held = resource_leases.resource_key("command", "a" * 64)
        free = resource_leases.resource_key("command", "b" * 64)
        with resource_leases.process_resource_claim(self.owner_root, held):
            claimed = self.child_claim(free)
        self.assertEqual(claimed.returncode, 0, claimed.stderr)

    def test_claim_rejects_symlink_file_when_supported(self):
        key = resource_leases.resource_key("command", "c" * 64)
        import hashlib
        filename = ".resource-" + hashlib.sha256(
            key.encode("utf-8")
        ).hexdigest() + ".claim"
        external = self.owner_root / "external.txt"
        external.write_text("do not change", encoding="utf-8")
        name = self.owner_root / filename
        try:
            name.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("Creating a symlink needs platform privileges.")
        with self.assertRaises(resource_leases.LeaseConflict):
            with resource_leases.process_resource_claim(self.owner_root, key):
                self.fail("The symlink claim path was trusted.")
        self.assertEqual(external.read_text(encoding="utf-8"), "do not change")


if __name__ == "__main__":
    unittest.main()
